"""Computer vision perception exceptions for AI TrafficOS.

Defines a clean, typed exception hierarchy for detector failures, corrupt inputs,
and unsupported tensor representations.
"""


class VisionDetectorError(Exception):
    """Base exception for all computer vision perception errors in AI TrafficOS."""


class InvalidInputFrameError(VisionDetectorError):
    """Raised when an input frame is None, empty, zero-dimensioned, or non-existent."""


class CorruptFrameError(VisionDetectorError):
    """Raised when an image payload is corrupted, undecodable, or contains NaN/Inf values."""


class UnsupportedInputFormatError(VisionDetectorError):
    """Raised when an unsupported input type or tensor dimensionality is passed to a detector."""


class ModelLoadError(VisionDetectorError):
    """Raised when model weights cannot be located, initialized, or parsed."""


class SingleFrameSpeedError(VisionDetectorError):
    """Raised when speed calculation is attempted on a single image without temporal tracking."""


class VideoProcessingError(VisionDetectorError):
    """Base exception for video ingest and processing errors."""


class VideoOpenError(VideoProcessingError):
    """Raised when a video file or stream cannot be opened or does not exist."""


class CorruptVideoError(VideoProcessingError):
    """Raised when a video file contains corrupt, truncated, or unreadable frames."""


class EmptyVideoError(VideoProcessingError):
    """Raised when a video file contains zero frames or yields an empty stream."""


class UnsupportedVideoFormatError(VideoProcessingError):
    """Raised when a video container or codec is unsupported."""

