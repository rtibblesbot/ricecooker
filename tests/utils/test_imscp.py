import os
import zipfile

from ricecooker.utils.imscp import flatten_single_child_topics
from ricecooker.utils.imscp import is_qti_resource
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

    # The organization wraps a single content-root topic; flattening collapses
    # that redundant level so the content root sits directly under the manifest.
    root_topic = manifest["children"][0]
    assert root_topic["title"] == "Evento's Solutions, servicios integrales (ESSI)"
    assert all(child.get("children") is None for child in root_topic["children"])

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


def test_collect_metadata_from_gitta(tmp_path):
    # gitta carries LOM <general> (title/language/keyword) and <rights> at the
    # manifest level; the parser lifts them into the node metadata dict.
    ims_dir = _extract("gitta_ims.zip", tmp_path)
    metadata = parse_imscp_manifest(ims_dir)["metadata"]
    assert metadata["title"] == "Databases"
    assert metadata["language"] == "en"
    assert len(metadata["keyword"]) == 15
    assert "Database Management" in metadata["keyword"]
    # rights/description is prefixed so it does not collide with general/description.
    assert metadata["rights_description"] == "GITTA 2000-2005"


def test_collect_metadata_lom_vocab_and_contribute(tmp_path):
    # Educational vocab terms live in <value><langstring>; contributors in VCARDs.
    leaf = _parse_leaf(
        tmp_path,
        '<resource identifier="RES" type="webcontent" href="p.html">'
        '<file href="p.html"/></resource>',
        item_body="<metadata><lom>"
        "<educational>"
        "<interactivityType><value><langstring>active</langstring></value></interactivityType>"
        "<learningResourceType><value><langstring>narrative text</langstring></value>"
        "</learningResourceType>"
        "</educational>"
        "<rights><description><langstring>Creative Commons Attribution-ShareAlike"
        "</langstring></description></rights>"
        "<lifeCycle><contribute><role><value><langstring>author</langstring></value>"
        "</role><entity>FN:Ada Lovelace</entity></contribute></lifeCycle>"
        "</lom></metadata>",
    )
    metadata = leaf["metadata"]
    assert metadata["interactivityType"] == "active"
    assert metadata["learningResourceType"] == "narrative text"
    assert metadata["rights_description"].startswith("Creative Commons")
    assert metadata["contribute"] == {
        "role": {"value": "author"},
        "entity": "FN:Ada Lovelace",
    }


def test_collect_metadata_external_location(tmp_path):
    # An <adlcp:location> under <metadata> points at an external LOM file, which
    # the parser resolves relative to the package directory.
    with open(os.path.join(str(tmp_path), "meta.xml"), "w", encoding="utf-8") as fh:
        fh.write(
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<lom xmlns="http://www.imsglobal.org/xsd/imsmd_rootv1p2p1">'
            "<general><title><langstring>External Title</langstring></title>"
            "<keyword><langstring>alpha</langstring></keyword></general></lom>"
        )
    _write_manifest(
        str(tmp_path),
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<manifest xmlns="http://www.imsproject.org/xsd/imscp_rootv1p1p2" '
        'xmlns:adlcp="http://www.adlnet.org/xsd/adlcp_rootv1p2" identifier="M">'
        "<metadata><schema>IMS CONTENT</schema>"
        "<adlcp:location>meta.xml</adlcp:location></metadata>"
        '<organizations default="ORG"><organization identifier="ORG"><title>Org</title>'
        '<item identifier="IT" identifierref="RES"><title>Leaf</title></item>'
        "</organization></organizations>"
        '<resources><resource identifier="RES" type="webcontent" href="p.html">'
        '<file href="p.html"/></resource></resources></manifest>',
    )
    metadata = parse_imscp_manifest(str(tmp_path))["metadata"]
    assert metadata["title"] == "External Title"
    # A lone <keyword> collects as a single value; the mapping normalizes to a list.
    assert metadata["keyword"] == "alpha"


def test_leaf_source_id_from_identifier(tmp_path):
    ims_dir = _extract("test_quiz.zip", tmp_path)
    manifest = parse_imscp_manifest(ims_dir)
    leaf = manifest["children"][0]["children"][0]
    assert leaf["source_id"] == "ITEM-56C2D9D9-ACA6-40B5-8A5D-A70DB05370FC"


def test_xml_base_applied_to_index_file(tmp_path):
    # index_file must carry the same xml:base offset as the resource's members,
    # or it resolves to a nonexistent path and the whole resource is dropped.
    _write_manifest(
        str(tmp_path),
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<manifest xmlns="http://www.imsproject.org/xsd/imscp_rootv1p1p2" identifier="M">'
        '<organizations default="ORG"><organization identifier="ORG"><title>Org</title>'
        '<item identifier="IT" identifierref="RES"><title>Leaf</title></item>'
        "</organization></organizations>"
        '<resources><resource identifier="RES" type="webcontent" '
        'xml:base="content/" href="start.html"><file href="start.html"/>'
        "</resource></resources></manifest>",
    )
    assert leaf["index_file"] == "content/start.html"
    assert leaf["files"] == ["content/start.html"]


def test_masteryscore_element_surfaced(tmp_path):
    # <adlcp:masteryscore> is a child element of the item, not an attribute; the
    # parser must still surface it for the assessment classifier.
    leaf = _parse_leaf(
        tmp_path,
        '<resource identifier="RES" type="webcontent" href="q.html">'
        '<file href="q.html"/></resource>',
        item_body="<adlcp:masteryscore>80</adlcp:masteryscore>",
    )
    assert leaf["masteryscore"] == "80"


def test_is_qti_resource():
    # QTI resources are identified by the spec's ``imsqti_`` type prefix.
    assert is_qti_resource("imsqti_xmlv1p2")
    assert is_qti_resource("imsqti_test_xmlv1p2")
    assert not is_qti_resource("webcontent")
    assert not is_qti_resource("")
    assert not is_qti_resource(None)


def test_qti_resource_files_derived(tmp_path):
    # A QTI resource is parsed like webcontent (files/index derived) so the
    # decomposer can reject it intentionally rather than silently skip it.
    leaf = _parse_leaf(
        tmp_path,
        '<resource identifier="RES" type="imsqti_xmlv1p2" href="q.xml">'
        '<file href="q.xml"/></resource>',
    )
    assert is_qti_resource(leaf["type"])
    assert leaf["files"] == ["q.xml"]


def test_flatten_single_child_topics():
    # A topic whose sole child is another topic collapses; the child keeps its
    # own title. Leaf-only and multi-child topics are left untouched.
    tree = {
        "source_id": "org",
        "title": "Organization",
        "children": [
            {
                "source_id": "root",
                "title": "Content Root",
                "children": [
                    {"source_id": "a", "title": "A"},
                    {"source_id": "b", "title": "B"},
                ],
            }
        ],
    }
    flat = flatten_single_child_topics(tree)
    assert flat["source_id"] == "root"
    assert flat["title"] == "Content Root"
    assert [c["source_id"] for c in flat["children"]] == ["a", "b"]


def test_flatten_keeps_leaf_only_topic(tmp_path):
    # test_quiz's organization holds a single *leaf* (not a topic), so the
    # organization level must be preserved, not collapsed onto the leaf.
    ims_dir = _extract("test_quiz.zip", tmp_path)
    manifest = parse_imscp_manifest(ims_dir)
    org = manifest["children"][0]
    assert org["title"] == "Organization"
    assert len(org["children"]) == 1
    assert org["children"][0].get("children") is None


def test_dangling_reference_dropped(tmp_path):
    # An item pointing at a missing resource is left without files rather than
    # crashing; the tree still parses.
    leaf = _parse_leaf(tmp_path, "", identifierref="MISSING")
    assert "files" not in leaf
    assert leaf["source_id"] == "IT"


def test_cyclic_dependency_does_not_recurse_forever(tmp_path):
    # A malformed/untrusted manifest with a <dependency> cycle (A→B→A) must not
    # send file derivation into unbounded recursion; each member appears once.
    _write_manifest(
        str(tmp_path),
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<manifest xmlns="http://www.imsproject.org/xsd/imscp_rootv1p1p2" identifier="M">'
        '<organizations default="ORG"><organization identifier="ORG"><title>Org</title>'
        '<item identifier="IT" identifierref="A"><title>Leaf</title></item>'
        "</organization></organizations>"
        "<resources>"
        '<resource identifier="A" type="webcontent" href="a.html">'
        '<file href="a.html"/><dependency identifierref="B"/></resource>'
        '<resource identifier="B" type="webcontent" href="b.html">'
        '<file href="b.html"/><dependency identifierref="A"/></resource>',
        identifierref="A",
    )
    assert leaf["files"] == ["a.html", "b.html"]
