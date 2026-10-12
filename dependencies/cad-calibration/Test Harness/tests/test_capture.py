from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch
from PIL import Image, ImageDraw
from frame_harness.capture import usable_capture


class CaptureTests(unittest.TestCase):
    def test_clipped_readback_with_small_nonuniform_patch_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp)/'capture.png'
            for background, patch_color in [('white', 'gray'), ('black', 'gray')]:
                image = Image.new('RGB', (1280, 720), background)
                ImageDraw.Draw(image).rectangle((0, 0, 30, 30), fill=patch_color)
                image.save(path, compress_level=0)
                self.assertFalse(usable_capture(path))

    def test_session_rejects_blank_image_even_when_recorder_and_save_report_success(self):
        from frame_harness.session import DriveSession
        from frame_harness.models import HarnessProject
        from frame_harness.build import write_json
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);session=DriveSession(HarnessProject())
            session.control=root;session.launch={};session.process=Mock()
            session.process.poll.return_value=None
            identity=dict(job_id='job',session_id=session.id)
            write_json(root/'completion.json',identity|dict(status='completed'))
            write_json(root/'capture_status.json',identity|dict(done=True,success=True,required={'final':True}))
            write_json(root/'final.png.json',identity|dict(success=True))
            Image.new('RGB',(1280,720),'white').save(root/'final.png')
            with patch.object(session,'start'),patch.object(session,'command'):
                with self.assertRaisesRegex(RuntimeError,'blank'):
                    session.execute(dict(id='job',duration=25),root,root)

    def test_valid_png_readback_can_still_be_blank(self):
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'capture.png'
            for color in ('white','black','red'):
                Image.new('RGB',(1280,720),color).save(path,compress_level=0)
                self.assertGreater(path.stat().st_size,1024)
                self.assertFalse(usable_capture(path),color)
            image=Image.new('RGB',(128,128),'gray')
            ImageDraw.Draw(image).rectangle((20,20,100,100),fill='blue')
            image.save(path,compress_level=0)
            self.assertTrue(usable_capture(path))
            path.write_bytes(b'not a PNG'*1000)
            self.assertFalse(usable_capture(path))
            path.unlink()
            self.assertFalse(usable_capture(path))


if __name__=='__main__': unittest.main()
