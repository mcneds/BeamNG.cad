"""Basic image integrity gate; content still requires rendered mesh review."""
from pathlib import Path
from PIL import Image, UnidentifiedImageError


def usable_capture(path):
    """Reject absent, corrupt and blank readbacks, including valid white PNGs."""
    path = Path(path)
    try:
        if not path.is_file() or path.stat().st_size < 1024:
            return False
        with Image.open(path) as image:
            image.load()
            if image.format != 'PNG' or min(image.size) < 32:
                return False
            if 'A' in image.getbands() and image.getchannel('A').getextrema()[1] == 0:
                return False
            # Uniform colored images have different channel values but no spatial
            # information. Compare each channel's spatial range independently.
            rgb = image.convert('RGB')
            if not any(high-low > 2 for low, high in rgb.getextrema()):
                return False
            # Match the native readback gate. A few nonwhite pixels in an
            # otherwise clipped image are not usable rendered evidence.
            width, height = rgb.size
            samples = [rgb.getpixel((min(width-1, int((x+.5)*width/64)),
                                     min(height-1, int((y+.5)*height/36))))
                       for y in range(36) for x in range(64)]
            white = sum(min(pixel) >= 250 for pixel in samples)
            black = sum(max(pixel) <= 5 for pixel in samples)
            return max(white, black)/len(samples) < .99
    except (OSError, ValueError, UnidentifiedImageError):
        return False
