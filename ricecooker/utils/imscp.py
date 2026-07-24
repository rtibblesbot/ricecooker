"""Parse an extracted IMS Content Package (``imsmanifest.xml``) into a tree of dicts.

Ported from ``learningequality/imscp`` ``core.py`` to stdlib
:mod:`xml.etree.ElementTree`. Manifests declare varied default namespaces
(``imscp_rootv1p1p2``, ``imscp_v1p1``), so every ``find``/``findall`` uses a
``{*}`` wildcard rather than a fixed namespace map.
"""

import io
import logging
import os
import re
from xml.etree import ElementTree as ET

import chardet

LOGGER = logging.getLogger(__name__)

XML_BASE = "{http://www.w3.org/XML/1998/namespace}base"
XML_LANG = "{http://www.w3.org/XML/1998/namespace}lang"

QTI_RESOURCE_TYPE_PREFIX = "imsqti_"

# LOM sections and the fields lifted out of each, keyed by LOM element name.
LOM_METADATA_KEYS = {
    "general": ["title", "description", "language", "keyword"],
    "rights": ["cost", "copyrightAndOtherRestrictions", "description"],
    "educational": [
        "interactivityType",
        "interactivityLevel",
        "learningResourceType",
        "intendedEndUserRole",
        "difficulty",
    ],
    "lifeCycle": ["contribute"],
}


def is_qti_resource(resource_type):
    """True when ``resource_type`` names a QTI resource (spec-defined ``imsqti_`` prefix)."""
    return bool(resource_type) and resource_type.startswith(QTI_RESOURCE_TYPE_PREFIX)


def parse_imscp_manifest(ims_dir):
    """Parse ``imsmanifest.xml`` in ``ims_dir`` into the manifest tree.

    Returns ``{"identifier", "title", "metadata", "children": [node, ...]}``
    where each ``node`` is a topic (``{"source_id", "title", "children"}``) or a
    webcontent leaf (``{"source_id", "title", "type", "index_file", "href",
    "scormtype", "files"}``). ``files`` are archive-member paths relative to
    ``ims_dir``.
    """
    root = _read_manifest(os.path.join(ims_dir, "imsmanifest.xml"))

    metadata = collect_metadata(root, ims_dir)

    resources = {
        r.get("identifier"): r for r in root.findall("{*}resources/{*}resource")
    }

    children = []
    for org in root.findall("{*}organizations/{*}organization"):
        node = _walk_items(org, ims_dir)
        _collect_resources(node, resources)
        children.append(flatten_single_child_topics(node))

    return {
        "identifier": root.get("identifier"),
        "title": metadata.get("title"),
        "metadata": metadata,
        "children": children,
    }


def _read_manifest(manifest_path):
    """Parse the manifest, falling back to detected encoding on a parse error."""
    try:
        return ET.parse(manifest_path).getroot()
    except ET.ParseError:
        # Some manifests declare UTF-8 but contain other-encoded bytes; detect the
        # real encoding, decode, and re-parse from re-encoded UTF-8 bytes.
        with open(manifest_path, "rb") as f:
            data = f.read()
        encoding = chardet.detect(data)["encoding"]
        if encoding is None:
            # Nothing to re-decode from; the manifest is simply not parseable.
            raise
        return ET.parse(io.BytesIO(data.decode(encoding).encode("utf-8"))).getroot()


def _strip_ns(key):
    """Strip a ``{namespace}`` prefix off an attribute key."""
    return re.sub(r"^\{.*\}", "", key)


def _element_text(elem):
    """Concatenate all descendant text/tail (ignoring ``<br>``), stripped."""
    if elem is None:
        return ""
    return "".join(elem.itertext()).strip()


def contained_path(root, member):
    """Resolve ``member`` under ``root``; return the path, or None if it escapes.

    Manifest hrefs, file paths and metadata locations are all untrusted, so a
    ``../`` traversal must not read files from outside the extracted package (or
    write outside the staging directory a leaf is assembled in).
    """
    root_abs = os.path.abspath(root)
    target = os.path.abspath(os.path.join(root_abs, member))
    if target != root_abs and not target.startswith(root_abs + os.sep):
        return None
    return target


def _lom_text(elem):
    """The stripped text of a LOM element, or None when empty."""
    return (
        elem.text.strip()
        if elem is not None and elem.text and elem.text.strip()
        else None
    )


def _extract_lom_text(elem, preferred_language):
    """Read text from a LOM field, handling its several shapes.

    Handles ``<string language="en">``/``<langstring xml:lang="en">`` (returning a
    preferred-language match, the single value, or a list), ``<source>/<value>``
    pairs, and bare element text.
    """
    strings = elem.findall("{*}string") or elem.findall("{*}langstring")
    if strings:
        if preferred_language is not None:
            for s in strings:
                lang = s.get("language", "") or s.get(XML_LANG, "")
                if lang.startswith(preferred_language):
                    return _lom_text(s)
        if len(strings) == 1:
            return _lom_text(strings[0])
        return [_lom_text(s) for s in strings]

    # A LOM vocabulary term is ``<value><langstring>term</langstring></value>``
    # (or plain ``<value>term</value>``); recurse so the term text is read, not
    # the whitespace between ``<value>`` and its child.
    value = elem.find("{*}value")
    if value is not None:
        return _extract_lom_text(value, preferred_language)

    return _lom_text(elem)


def _extract_contribute(contrib_elem):
    """Extract a lifeCycle ``<contribute>`` entry as ``{"role", "entity"}``."""
    result = {}
    role = contrib_elem.find("{*}role")
    if role is not None:
        # The role vocabulary term sits in ``<value>`` (bare or langstring-wrapped).
        role_value = _extract_lom_text(role, None)
        if role_value:
            result["role"] = {"value": role_value}
    entity = contrib_elem.find("{*}entity")
    if entity is not None and entity.text:
        result["entity"] = entity.text
    return result


def _get_lom_section(metadata_elem, tag):
    """The LOM ``<tag>`` section, whether wrapped in ``<lom>`` or bare."""
    section = metadata_elem.find("{*}lom/{*}" + tag)
    if section is not None:
        return section
    return metadata_elem.find("{*}" + tag)


def _detect_language(metadata_elem):
    """The preferred language declared in LOM ``<general><language>``."""
    general = _get_lom_section(metadata_elem, "general")
    if general is not None:
        return _lom_text(general.find("{*}language"))
    return None


def _resolve_metadata_elem(elem, ims_dir):
    """The ``<metadata>`` of ``elem``, following an external ``adlcp:location`` ref."""
    metadata_elem = elem.find("{*}metadata")
    if metadata_elem is None:
        return None
    location = metadata_elem.find("{*}location")
    if location is not None and location.text:
        ext_path = contained_path(ims_dir, location.text.strip())
        if ext_path and os.path.isfile(ext_path):
            try:
                return ET.parse(ext_path).getroot()
            except ET.ParseError:
                LOGGER.warning(
                    "IMSCP: could not parse external metadata %s", location.text
                )
    return metadata_elem


def _collect_field(section, field, preferred_language):
    """The value of LOM ``field`` in ``section``: scalar when single, list when repeated."""
    elems = section.findall("{*}" + field)
    if not elems:
        return None
    if field == "contribute":
        values = [_extract_contribute(e) for e in elems]
    else:
        values = [_extract_lom_text(e, preferred_language) for e in elems]
    return values[0] if len(values) == 1 else values


def collect_metadata(elem, ims_dir):
    """Extract the raw LOM metadata dict from ``elem``'s ``<metadata>``.

    Covers the sections named in :data:`LOM_METADATA_KEYS`. Mapping onto
    content-node fields is done separately by
    :func:`~ricecooker.utils.SCORM_metadata.metadata_dict_to_content_node_fields`.
    """
    metadata_elem = _resolve_metadata_elem(elem, ims_dir)
    if metadata_elem is None:
        return {}

    preferred_language = _detect_language(metadata_elem)

    metadata = {}
    for tag, fields in LOM_METADATA_KEYS.items():
        section = _get_lom_section(metadata_elem, tag)
        if section is None:
            continue
        for field in fields:
            value = _collect_field(section, field, preferred_language)
            if value is not None:
                # Prefix rights fields so ``rights/description`` does not collide
                # with ``general/description``.
                key = "rights_" + field if tag == "rights" else field
                metadata[key] = value
    return metadata


def _walk_items(elem, ims_dir):
    """Build an item/topic dict from ``elem`` and recurse into child ``<item>``s."""
    node = {_strip_ns(k): v for k, v in elem.attrib.items()}

    title = _element_text(elem.find("{*}title"))
    if title:
        node["title"] = title

    # ``<adlcp:masteryscore>`` is a child element of the item (not an attribute),
    # so it is not captured by the attrib copy above. Surface it for the
    # assessment classifier, which treats a mastery score as an exercise signal.
    mastery = _element_text(elem.find("{*}masteryscore"))
    if mastery:
        node["masteryscore"] = mastery

    metadata = collect_metadata(elem, ims_dir)
    if metadata:
        node["metadata"] = metadata

    children = [_walk_items(item, ims_dir) for item in elem.findall("{*}item")]
    if children:
        node["children"] = children

    return node


def _collect_resources(item, resources, index=1):
    """Resolve resource references onto leaf items; recurse into topics.

    ``index`` is the item's 1-based position among its siblings, used for the
    ``item{n}`` source_id fallback when an identifier is blank (ported from
    legacy ricecooker_utils, not core.py).
    """
    item["source_id"] = item.get("identifier") or "item{}".format(index)

    children = item.get("children")
    if children:
        for child_index, child in enumerate(children, start=1):
            _collect_resources(child, resources, child_index)
    elif item.get("identifierref"):
        resource = resources.get(item["identifierref"])
        if resource is None:
            LOGGER.warning(
                "IMSCP: item %s references missing resource %s",
                item["source_id"],
                item["identifierref"],
            )
            return
        # The item's own attributes win — a resource carries its own
        # ``identifier``, which must not displace the item's identity.
        for key, value in resource.attrib.items():
            item.setdefault(_strip_ns(key), value)
        resource_type = resource.get("type")
        # Both webcontent and QTI resources carry their own file members; QTI
        # resources are rejected downstream, but deriving their files keeps the
        # leaf self-describing. Other (unknown) resource types are left as-is.
        if resource_type == "webcontent" or is_qti_resource(resource_type):
            href = resource.get("href")
            if href:
                # ``index_file`` must carry the same ``xml:base`` offset that
                # _derive_files applies to the resource's members, or it will
                # not resolve to a real extracted path.
                item["index_file"] = (resource.get(XML_BASE) or "") + href
            item["files"] = _derive_files(resource, resources)
            item.setdefault("scormtype", None)


def _derive_files(resource, resources, seen=None, visited=None):
    """Own ``<file>`` members plus flattened ``<dependency>`` files, order-preserving."""
    if seen is None:
        seen = set()
    # Track resources already on the dependency chain so a cyclic <dependency>
    # (A→B→A, possible in a malformed/untrusted manifest) cannot recurse forever.
    if visited is None:
        visited = set()
    identifier = resource.get("identifier")
    if identifier in visited:
        return []
    visited.add(identifier)

    base = resource.get(XML_BASE) or ""
    files = []
    for fe in resource.findall("{*}file"):
        href = fe.get("href")
        if not href:
            continue
        path = base + href
        if path not in seen:
            seen.add(path)
            files.append(path)

    for dep in resource.findall("{*}dependency"):
        dep_ref = dep.get("identifierref")
        dep_resource = resources.get(dep_ref)
        if dep_resource is None:
            LOGGER.warning(
                "IMSCP: resource %s depends on missing resource %s",
                identifier,
                dep_ref,
            )
            continue
        files.extend(_derive_files(dep_resource, resources, seen, visited))

    return files


# Keys naming a node's identity/shape; LOM descriptive metadata must not
# overwrite them.
_NODE_IDENTITY_KEYS = frozenset({"source_id", "title", "kind", "children", "files"})


def lom_content_fields(node_dict):
    """Map a parsed node's raw LOM ``metadata`` to content-node fields."""
    return metadata_dict_to_content_node_fields(node_dict.get("metadata") or {})


def merge_lom_fields(built, fields):
    """Copy non-identity LOM-derived ``fields`` onto a built tree dict."""
    for key, value in fields.items():
        if key not in _NODE_IDENTITY_KEYS:
            built.setdefault(key, value)


def flatten_single_child_topics(node):
    """Collapse a topic whose only child is itself a topic into that child.

    IMS packages routinely wrap their whole tree in an ``<organization>`` holding
    one content-root ``<item>``; merging the two removes the redundant level.
    Leaf-only topics are left untouched. Ported from ricecooker PR #468.
    """
    children = node.get("children")
    if not children:
        return node

    node["children"] = [flatten_single_child_topics(child) for child in children]

    if len(node["children"]) == 1 and node["children"][0].get("children"):
        only_child = node["children"][0]
        if not only_child.get("title"):
            only_child["title"] = node.get("title")
        if not only_child.get("metadata") and node.get("metadata"):
            only_child["metadata"] = node["metadata"]
        return only_child

    return node
