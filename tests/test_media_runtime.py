"""Exercise the installed native video tooling without AI models or a GPU."""

import imageio.v2 as imageio
import numpy as np

from esp_image_server.video_generator import require_video_export_dependencies


def test_bundled_ffmpeg_encodes_and_decodes_mp4(tmp_path):
    require_video_export_dependencies()
    output = tmp_path / "tiny-video.mp4"
    with imageio.get_writer(output, fps=4) as writer:
        for value in (0, 80, 160, 255):
            writer.append_data(np.full((32, 32, 3), value, dtype=np.uint8))
    with imageio.get_reader(output) as reader:
        assert reader.count_frames() == 4
        assert reader.get_data(0).shape == (32, 32, 3)
    assert output.stat().st_size > 0
