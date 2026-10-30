import tempfile
import unittest
from pathlib import Path
import numpy as np
from PIL import Image
from simscene.worker.video import VideoRecorder
from simscene.video_tools import inspect


class VideoColorTest(unittest.TestCase):
    def test_encoded_sdr_roundtrip_preserves_neutrals_and_chromatic_patches(self):
        # This detects the real legacy filter-order failure: RGB was implicitly
        # converted to YUV before an override incorrectly labelled it GBR/full.
        colors=[(100,100,100),(223,223,223),(70,169,184),(59,109,148),(221,175,73)]
        frame=np.zeros((180,320,3),dtype=np.uint8)
        for i,color in enumerate(colors):frame[:,i*64:(i+1)*64]=color
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);recorder=VideoRecorder(root/'capture.mp4',30,320,180)
            for _ in range(6):recorder.write(frame)
            record=recorder.close();report=inspect(record['path'],root/'decoded',1,record)
            self.assertTrue(report['simulation_timeline']['passed'])
            with Image.open(report['representative_frames'][0]['path']) as decoded:
                for i,color in enumerate(colors):
                    actual=decoded.getpixel((i*64+32,90))
                    self.assertLessEqual(max(abs(a-b) for a,b in zip(color,actual)),3,(color,actual))
