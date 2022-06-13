from __future__ import annotations

import logging
from dataclasses import dataclass, field

# from functools import wraps
from typing import Optional, Tuple, TypeVar

import apache_beam as beam

from .openers import open_url, open_with_xarray
from .patterns import FileType, Index
from .storage import CacheFSSpecTarget

logger = logging.getLogger(__name__)

# From https://beam.apache.org/contribute/ptransform-style-guide/
#
# Do:
# - Expose every major data-parallel task accomplished by your library as a
#   composite PTransform. This allows the structure of the transform to evolve
#   transparently to the code that uses it: e.g. something that started as a
#   ParDo can become a more complex transform over time.
# - Expose large, non-trivial, reusable sequential bits of the transform’s code,
#   which others might want to reuse in ways you haven’t anticipated, as a regular
#   function or class library. The transform should simply wire this logic together.
#   As a side benefit, you can unit-test those functions and classes independently.
#   Example: when developing a transform that parses files in a custom data format,
#   expose the format parser as a library; likewise for a transform that implements
#   a complex machine learning algorithm, etc.
# - In some cases, this may include Beam-specific classes, such as CombineFn,
#   or nontrivial DoFns (those that are more than just a single @ProcessElement
#   method). As a rule of thumb: expose these if you anticipate that the full
#   packaged PTransform may be insufficient for a user’s needs and the user may want
#   to reuse the lower-level primitive.
#
# Do not:
# - Do not expose the exact way the transform is internally structured.
#   E.g.: the public API surface of your library usually (with exception of the
#   last bullet above) should not expose DoFn, concrete Source or Sink classes,
#   etc., in order to avoid presenting users with a confusing choice between
#   applying the PTransform or using the DoFn/Source/Sink.

# In the spirit of "[t]he transform should simply wire this logic together",
# the goal is to put _as little logic as possible_ in this module.
# Ideally each PTransform should be a simple Map or DoFn calling out to function
# from other modules


T = TypeVar("T")
Indexed = Tuple[Index, T]


def _add_keys(func):
    """Convenience decorator to remove and re-add keys to items in a Map"""
    annotations = func.__annotations__.copy()
    arg_name, annotation = next(iter(annotations.items()))
    annotations[arg_name] = Tuple[Index, annotation]
    return_annotation = annotations["return"]
    annotations["return"] = Tuple[Index, return_annotation]

    # @wraps(func)  # doesn't work for some reason
    def wrapper(arg, **kwargs):
        key, item = arg
        result = func(item, **kwargs)
        return key, result

    wrapper.__annotations__ = annotations
    return wrapper


# This has side effects if using a cache
@dataclass
class OpenURLWithFSSpec(beam.PTransform):
    """Open indexed string-based URLs with fsspec.

    :param cache: If provided, data will be cached in the object before opening.
    :param secrets: If provided these secrets will be injected into the URL as a query string.
    :param open_kwargs: Extra arguments passed to fsspec.open.
    """

    cache: Optional[CacheFSSpecTarget] = None
    secrets: Optional[dict] = None
    open_kwargs: Optional[dict] = None

    def expand(self, pcoll):
        return pcoll | "Open with fsspec" >> beam.Map(
            _add_keys(open_url),
            cache=self.cache,
            secrets=self.secrets,
            open_kwargs=self.open_kwargs,
        )


@dataclass
class OpenWithXarray(beam.PTransform):
    """Open indexed items with Xarray. Accepts either fsspec open-file-like objects
    or string URLs that can be passed directly to Xarray.

    :param file_type: Provide this if you know what type of file it is.
    :param load: Whether to eagerly load the data into memory ofter opening.
    :param copy_to_local: Whether to copy the file-like-object to a local path
       and pass the path to Xarray. Required for some file types (e.g. Grib).
       Can only be used with file-like-objects, not URLs.
    :param xarray_open_kwargs: Extra arguments to pass to Xarray's open function.
    """

    file_type: FileType = FileType.unknown
    load: bool = False
    copy_to_local: bool = False
    xarray_open_kwargs: Optional[dict] = field(default_factory=dict)

    def expand(self, pcoll):
        return pcoll | "Open with Xarray" >> beam.Map(
            _add_keys(open_with_xarray),
            file_type=self.file_type,
            load=self.load,
            copy_to_local=self.copy_to_local,
            xarray_open_kwargs=self.xarray_open_kwargs,
        )