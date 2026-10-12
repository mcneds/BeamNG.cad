"""Line-delimited progress protocol; ordinary log lines remain supported."""
import json
import time

def emit(phase, *, completed=None, total=None, detail=None, **values):
    print('CAD_PROGRESS '+json.dumps(dict(phase=phase,completed=completed,total=total,
          detail=detail,monotonic=time.monotonic(),**values),allow_nan=False),flush=True)
