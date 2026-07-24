import os
import zipfile

from ricecooker.utils.imscp import parse_imscp_manifest

FIXTURE_DIR = os.path.join(
    os.path.dirname(os.path.dirname(__file__)), "testcontent", "imscp"
)


def _extract(fixture_name, dest):
    """Extract a fixture IMSCP zip into ``dest`` and return the directory."""
    with zipfile.ZipFile(os.path.join(FIXTURE_DIR, fixture_name)) as zf:
        zf.extractall(dest)
    return str(dest)


def _manifest_leaves(node):
    """Yield every webcontent leaf (a node without ``children``) in the tree."""
    if node.get("children"):
        for child in node["children"]:
            yield from _manifest_leaves(child)
    else:
        yield node


def _iter_topics(node):
    """Yield every topic node (a node with ``children``) in the tree."""
    if node.get("children"):
        yield node
        for child in node["children"]:
            yield from _iter_topics(child)


def _write_manifest(directory, manifest_xml):
    with open(os.path.join(directory, "imsmanifest.xml"), "w", encoding="utf-8") as fh:
        fh.write(manifest_xml)


def _parse_leaf(tmp_path, resources, item_body="", identifierref="RES"):
    """Write a one-item manifest wrapping ``resources`` and return its parsed leaf."""
    _write_manifest(
        str(tmp_path),
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<manifest xmlns="http://www.imsproject.org/xsd/imscp_rootv1p1p2" '
        'xmlns:adlcp="http://www.adlnet.org/xsd/adlcp_rootv1p2" identifier="M">'
        '<organizations default="ORG"><organization identifier="ORG"><title>Org</title>'
        '<item identifier="IT" identifierref="{}"><title>Leaf</title>{}</item>'
        "</organization></organizations>"
        "<resources>{}</resources></manifest>".format(
            identifierref, item_body, resources
        ),
    )
    return parse_imscp_manifest(str(tmp_path))["children"][0]["children"][0]


def test_parse_test_quiz(tmp_path):
    ims_dir = _extract("test_quiz.zip", tmp_path)
    manifest = parse_imscp_manifest(ims_dir)

    assert len(manifest["children"]) == 1
    org = manifest["children"][0]
    assert org["title"] == "Organization"
    assert len(org["children"]) == 1

    leaf = org["children"][0]
    assert leaf["type"] == "webcontent"
    assert leaf["scormtype"] == "sco"
    assert leaf["index_file"].lower().endswith((".htm", ".html"))


def test_parse_eventos_nested_tree(tmp_path):
    ims_dir = _extract("eventos.zip", tmp_path)
    manifest = parse_imscp_manifest(ims_dir)

    org = manifest["children"][0]
    assert org["title"] == "Evento's Solutions, servicios integrales (ESSI)"

    leaves = list(_manifest_leaves(manifest))
    assert len(leaves) > 1

    # Every leaf carries its own html index plus flattened .js/.css dependencies.
    for leaf in leaves:
        assert leaf["type"] == "webcontent"
        assert any(f.lower().endswith((".htm", ".html")) for f in leaf["files"])


def test_parse_eventos_derives_dependency_files(tmp_path):
    ims_dir = _extract("eventos.zip", tmp_path)
    manifest = parse_imscp_manifest(ims_dir)

    # RES-...f46 ("El origen del proyecto") declares a <dependency> on COMMON_FILES.
    leaf = next(
        leaf
        for leaf in _manifest_leaves(manifest)
        if leaf["title"] == "El origen del proyecto"
    )
    files = leaf["files"]
    # Own file present.
    assert "el_origen_del_proyecto.html" in files
    # Flattened dependency members present (from the COMMON_FILES resource).
    assert "content.css" in files
    assert "SCORM_API_wrapper.js" in files
    # Order preserved, no duplicates.
    assert len(files) == len(set(files))
    assert files.index("el_origen_del_proyecto.html") < files.index("content.css")


def test_parse_gitta_deep_tree(tmp_path):
    ims_dir = _extract("gitta_ims.zip", tmp_path)
    manifest = parse_imscp_manifest(ims_dir)

    leaves = list(_manifest_leaves(manifest))
    assert len(leaves) > 1

    for topic in _iter_topics(manifest):
        assert isinstance(topic["title"], str)
        assert topic["title"] == topic["title"].strip()
        assert topic["title"]


def test_leaf_source_id_from_identifier(tmp_path):
    ims_dir = _extract("test_quiz.zip", tmp_path)
    manifest = parse_imscp_manifest(ims_dir)
    leaf = manifest["children"][0]["children"][0]
    assert leaf["source_id"] == "ITEM-56C2D9D9-ACA6-40B5-8A5D-A70DB05370FC"
