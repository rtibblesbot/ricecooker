import base64
import codecs
import mimetypes
import re

import chardet

BASE64_REGEX_STR = r"data:image\/([A-Za-z]*);base64,((?:[A-Za-z0-9+\/]{4})*(?:[A-Za-z0-9+\/]{2}==|[A-Za-z0-9+\/]{3}=)*)"
BASE64_REGEX = re.compile(BASE64_REGEX_STR, flags=re.IGNORECASE)

DATA_URI_BASE64_REGEX = re.compile(
    r"^data:([\w.+-]+/[\w.+-]+)?(?:;[\w-]+=[^;,]+)*;base64,([A-Za-z0-9+/=\s]+)$",
    flags=re.IGNORECASE,
)

# Pin extensions for the types single-file-cli emits, so they resolve the same
# on every supported Python (e.g. image/webp is absent from stdlib mimetypes
# before 3.11) rather than depending on the interpreter's mimetypes DB.
_MIMETYPE_EXTENSIONS = {
    "image/png": "png",
    "image/jpeg": "jpg",
    "image/gif": "gif",
    "image/svg+xml": "svg",
    "image/webp": "webp",
    "font/woff2": "woff2",
    "font/woff": "woff",
    "font/ttf": "ttf",
    # mimetypes guesses "xsl".
    "application/xml": "xml",
    # Absent from mimetypes from 3.12.
    "application/javascript": "js",
    # Absent from mimetypes before 3.12.
    "text/javascript": "js",
}


def get_base64_encoding(text):
    """get_base64_encoding: Get the first base64 match or None
    Args:
        text (str): text to check for base64 encoding
    Returns: First match in text
    """
    return BASE64_REGEX.search(text)


def get_base64_data_uri(text):
    """Match a base64 ``data:`` URI of any mimetype (group 1 = mimetype, group 2 = data), or None."""
    return DATA_URI_BASE64_REGEX.match(text)


_FORMATLESS_TYPES = {"application/octet-stream", "binary/octet-stream", "text/plain"}


def mimetype_from_content_type(content_type):
    if not content_type:
        return None
    return content_type.split(";")[0].strip().lower()


def ext_from_content_type(content_type):
    mimetype = mimetype_from_content_type(content_type)
    if not mimetype or mimetype in _FORMATLESS_TYPES:
        return None
    if mimetype in _MIMETYPE_EXTENSIONS:
        return _MIMETYPE_EXTENSIONS[mimetype]
    guessed = mimetypes.guess_extension(mimetype)
    return guessed.lstrip(".") if guessed else None


def ext_from_data_uri_mimetype(mimetype):
    """Map a ``data:`` URI mimetype to a file extension (no dot), or None if undeterminable."""
    if not mimetype or not mimetype.lower().startswith(("image/", "font/")):
        return None
    return ext_from_content_type(mimetype)


_C1_BYTES = re.compile(rb"[\x80-\x9f]")


def decode_text(data):
    try:
        return data.decode("utf-8"), "utf-8"
    except UnicodeDecodeError as e:
        encoding = (
            chardet.detect(data[e.start : e.start + 4096])["encoding"] or "latin-1"
        )
        try:
            codec = codecs.lookup(encoding).name
        except LookupError:
            encoding, codec = "latin-1", "iso8859-1"
        # chardet names cp1252 only when the sampled bytes include 0x80-0x9F.
        if codec == "iso8859-1" and _C1_BYTES.search(data):
            encoding = "cp1252"
        return data.decode(encoding, errors="surrogateescape"), encoding


def encode_text(text, encoding):
    return text.encode(encoding, errors="surrogateescape")


def write_base64_to_file(encoding, fpath_out):
    """write_base64_to_file: Convert base64 image to file
    Args:
        encoding (str): base64 encoded string
        fpath_out (str): path to file to write
    Returns: None
    """

    encoding_match = get_base64_encoding(encoding)

    assert encoding_match, "Error writing to file: Invalid base64 encoding"

    with open(fpath_out, "wb") as target_file:
        target_file.write(base64.decodebytes(encoding_match.group(2).encode("utf-8")))


def encode_file_to_base64(fpath_in, prefix):
    """encode_file_to_base64: gets base64 encoding of file
    Args:
        fpath_in (str): path to file to encode
        prefix (str): file data for encoding (e.g. 'data:image/png;base64,')
    Returns: base64 encoding of file
    """
    with open(fpath_in, "rb") as file_obj:
        return prefix + base64.b64encode(file_obj.read()).decode("utf-8")
