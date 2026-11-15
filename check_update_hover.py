import hashlib
import tempfile
import time
from pathlib import Path
from unittest.mock import patch
import customtkinter as ct
from customtkinter.windows.widgets.core_rendering import DrawEngine
from hover import AnimatedButton
import updater
import loaders

DrawEngine.preferred_drawing_method='polygon_shapes'
root=ct.CTk()
button=AnimatedButton(root,text='Test',fg_color='#302040',hover_color='#9060e0')
button.pack();root.update()
button._on_enter()
def pump():
    deadline=time.monotonic()+.22
    while time.monotonic()<deadline:root.update();time.sleep(.005)
pump()
assert button._fade_color=='#9060e0'
for _ in range(20):button._on_leave();button._on_enter()
button._on_leave();pump()
assert button._fade_color=='#302040' and button._fade_job is None
button._on_enter();button.configure(state='disabled');assert button._fade_job is None
button.destroy();root.update();root.destroy()
assert '1.16.5' in loaders.VERSIONS and '1.16.4' not in loaders.VERSIONS
assert updater.version_key('v2026.11.15.2')>updater.version_key(updater.VERSION)

class Response:
    def __enter__(self):return self
    def __exit__(self,*args):pass
    def raise_for_status(self):pass
    def iter_content(self,*args):return iter([b'MZverified-test'])

with tempfile.TemporaryDirectory() as folder:
    asset={'browser_download_url':'https://example.test/asset','size':15,
           'digest':'sha256:'+hashlib.sha256(b'MZverified-test').hexdigest()}
    asset['size']=len(b'MZverified-test')
    with patch.object(updater.requests,'get',return_value=Response()):
        stage=updater.download(asset,Path(folder)/'TUL4N.exe',lambda text:None)
        assert stage.read_bytes()==b'MZverified-test'
        asset['digest']='sha256:'+'0'*64
        try:updater.download(asset,Path(folder)/'TUL4N.exe',lambda text:None)
        except ValueError:pass
        else:raise AssertionError('Corrupted update accepted')
        assert not stage.exists()
print('PASS: hover reversal, cancellation, disabled/destroy, version list, update integrity and cleanup')

