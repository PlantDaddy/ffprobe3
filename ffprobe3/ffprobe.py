"""
Python wrapper for ffprobe command line tool. ffprobe must exist in the path.
"""
import functools
import operator
import os
import pipes
import platform
import subprocess
import re

from ffprobe3.exceptions import FFProbeError


class FFProbe:
    """
    FFProbe wraps the ffprobe command and pulls the data into an object form::
        metadata=FFProbe('multimedia-file.mov')
    """

    def __init__(self, path_to_video: str):
        self.path_to_video = path_to_video
        self.bit_re = re.compile(r'\ \d{1,8}\ [a-z]b')
        self.stream_re = re.compile(r'Duration: [0=9]+:')
        self.stream_index_re = re.compile(r'#[0-9]+:[0-9]+\(')

        try:
            with open(os.devnull, 'w') as tempf:
                subprocess.check_call(["ffprobe", "-h"], stdout=tempf, stderr=tempf)
        except FileNotFoundError:
            raise IOError('ffprobe not found.')

        stdout, stderr = self.probe(self.path_to_video, '-show_streams')
        stream = False
        self.streams = []
        self.video = []
        self.audio = []
        self.subtitle = []
        self.attachment = []
        self.container = []

        for line in stdout:
            if '[STREAM]' in line:
                stream = True
                data_lines = []
            elif '[/STREAM]' in line and stream:
                stream = False
                # noinspection PyUnboundLocalVariable
                self.streams.append(FFStream(data_lines))
            elif stream:
                data_lines.append(line)

        for line in stderr:
            if '[STREAM]' in line:
                stream = True
                data_lines = []
            elif '[/STREAM]' in line and stream:
                stream = False
                self.streams.append(FFStream(data_lines))
            elif stream:
                data_lines.append(line)

        for stream in self.streams:
            if stream.is_audio():
                self.audio.append(stream)
            elif stream.is_video():
                self.video.append(stream)
            elif stream.is_subtitle():
                self.subtitle.append(stream)
            elif stream.is_attachment():
                self.attachment.append(stream)

        # Matroska containers don't have bit_rate metadata, but it can still be parsed from stderr
        mkvout, mkverr = self.probe(self.path_to_video)
        for line in mkverr:
            if self.stream_re.search(line):
                bit_match = self.bit_re.search(line).group()
                bit_match = re.sub("[^0-9]", "", bit_match)
                self.container.append(FFContainer(['container_bitrate={}'.format(bit_match)]))

    def __repr__(self) -> str:
        return "<FFprobe: {video}, {audio}, {subtitle}, {attachment}>".format(**vars(self))

    def probe(self, video_path: str, *args: str) -> str:
        if os.path.isfile(self.path_to_video):
            if platform.system() == 'Windows':
                if len(args) == 0:
                    cmd = ["ffprobe", video_path]
                else:
                    cmd = ["ffprobe", args, video_path]
            else:
                if len(args) == 0:
                    cmd = ["ffprobe" + pipes.quote(video_path)]
                else:
                    cmd = ["ffprobe", args + pipes.quote(video_path)]
            stdout, stderr = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, shell=True).communicate()
            stdout = stdout.decode('UTF-8').splitlines()
            stderr = stderr.decode('UTF-8').splitlines()
            return stdout, stderr
        else:
            raise IOError('No such media file ' + self.path_to_video)


class FFStream:
    """
    An object representation of an individual stream in a multimedia file.
    """

    def __init__(self, data_lines: list):
        for line in data_lines:
            self.__dict__.update({key: value for key, value, *_ in [line.strip().split('=')]})

            try:
                self.__dict__['framerate'] = round(
                    functools.reduce(
                        operator.truediv, map(int, self.__dict__.get('avg_frame_rate', '').split('/'))
                    )
                )

            except (ValueError, ZeroDivisionError):
                self.__dict__['framerate'] = None

    def __repr__(self) -> dict:
        if self.is_video():
            template = "<Stream: #{index} [{codec_type}] {codec_long_name}, {framerate}, ({width}x{height})>"

        elif self.is_audio():
            template = "<Stream: #{index} [{codec_type}] {codec_long_name}, channels: {channels} ({channel_layout}), " \
                       "{sample_rate}Hz> "

        elif self.is_subtitle() or self.is_attachment():
            template = "<Stream: #{index} [{codec_type}] {codec_long_name}>"

        else:
            template = ''

        return template.format(**self.__dict__)

    def is_audio(self) -> dict:
        """
        Is this stream labelled as an audio stream?
        """
        return self.__dict__.get('codec_type', None) == 'audio'

    def is_video(self) -> dict:
        """
        Is the stream labelled as a video stream.
        """
        return self.__dict__.get('codec_type', None) == 'video'

    def is_subtitle(self) -> dict:
        """
        Is the stream labelled as a subtitle stream.
        """
        return self.__dict__.get('codec_type', None) == 'subtitle'

    def is_attachment(self) -> dict:
        """
        Is the stream labelled as a attachment stream.
        """
        return self.__dict__.get('codec_type', None) == 'attachment'

    def frame_size(self) -> tuple:
        """
        Returns the pixel frame size as an integer tuple (width,height) if the stream is a video stream.
        Returns None if it is not a video stream.
        """
        size = None
        if self.is_video():
            width = self.__dict__['width']
            height = self.__dict__['height']

            if width and height:
                try:
                    size = (int(width), int(height))
                except ValueError:
                    raise FFProbeError("None integer size {}:{}".format(width, height))
        else:
            return None

        return size

    def pixel_format(self) -> dict:
        """
        Returns a string representing the pixel format of the video stream. e.g. yuv420p.
        Returns none is it is not a video stream.
        """
        return self.__dict__.get('pix_fmt', None)

    def frames(self) -> int:
        """
        Returns the length of a video stream in frames. Returns 0 if not a video stream.
        """
        if self.is_video() or self.is_audio():
            try:
                frame_count = int(self.__dict__.get('nb_frames', ''))
            except ValueError:
                raise FFProbeError('None integer frame count')
        else:
            frame_count = 0

        return frame_count

    def duration_seconds(self) -> int:
        """
        Returns the runtime duration of the video stream as a floating point number of seconds.
        Returns 0.0 if not a video stream.
        """
        if self.is_video() or self.is_audio():
            try:
                duration = float(self.__dict__.get('duration', ''))
            except ValueError:
                raise FFProbeError('None numeric duration')
        else:
            duration = 0.0

        return duration

    def language(self) -> str:
        """
        Returns language tag of stream. e.g. eng
        """
        return self.__dict__.get('TAG:language', None)

    def codec(self) -> str:
        """
        Returns a string representation of the stream codec.
        """
        return self.__dict__.get('codec_name', None)

    def codec_description(self) -> str:
        """
        Returns a long representation of the stream codec.
        """
        return self.__dict__.get('codec_long_name', None)

    def codec_tag(self) -> str:
        """
        Returns a short representative tag of the stream codec.
        """
        return self.__dict__.get('codec_tag_string', None)

    def bit_rate(self) -> int:
        """
        Returns bit_rate as an integer in bps
        """
        try:
            return int(self.__dict__.get('bit_rate', ''))
        except ValueError:
            raise FFProbeError('None integer bit_rate')

class FFContainer:
    """
    An object representation of a container for media streams
    """
    def __init__(self, data_lines):
        for line in data_lines:
            self.__dict__.update({key: value for key, value in [line.strip().split('=')]})

    def container_bitrate(self) -> int:
        """
        Returns container_bitrate as an integer in bps
        """
        try:
            return int(self.__dict__.get('container_bitrate', ''))
        except ValueError:
            raise FFProbeError('None integer container_bitrate')
