from le_utils.constants import licenses
from le_utils.constants.labels import learning_activities
from le_utils.constants.labels import needs
from le_utils.constants.labels import resource_type

from ricecooker.utils.SCORM_metadata import extract_lifecycle_contributors
from ricecooker.utils.SCORM_metadata import infer_beginner_level_from_difficulty
from ricecooker.utils.SCORM_metadata import infer_license_from_rights
from ricecooker.utils.SCORM_metadata import map_scorm_to_educator_resource_types
from ricecooker.utils.SCORM_metadata import metadata_dict_to_content_node_fields


def test_activities_downgrade_when_not_interactive():
    # A simulation with no interactivity signal downgrades EXPLORE -> READ.
    assert map_scorm_to_le_utils_activities({"learningResourceType": "simulation"}) == [
        learning_activities.READ
    ]
    # A diagram (also EXPLORE) downgrades to WATCH, not READ.
    assert map_scorm_to_le_utils_activities({"learningResourceType": "diagram"}) == [
        learning_activities.WATCH
    ]


def test_activities_kept_when_interactive():
    assert map_scorm_to_le_utils_activities(
        {"learningResourceType": "simulation", "interactivityType": "active"}
    ) == [learning_activities.EXPLORE]


def test_activities_dedupe_and_list_input():
    assert map_scorm_to_le_utils_activities(
        {
            "learningResourceType": ["exercise", "questionnaire"],
            "interactivityLevel": "high",
        }
    ) == [learning_activities.PRACTICE]


def test_educator_resource_types_from_type_and_role():
    result = map_scorm_to_educator_resource_types(
        {"learningResourceType": "exercise", "intendedEndUserRole": "teacher"}
    )
    assert resource_type.EXERCISE in result
    assert resource_type.LESSON_PLAN in result


def test_beginner_level_from_difficulty():
    assert infer_beginner_level_from_difficulty({"difficulty": "easy"}) == [
        needs.FOR_BEGINNERS
    ]
    assert infer_beginner_level_from_difficulty({"difficulty": "difficult"}) == []


def test_infer_license_from_rights_description():
    license_id, description = infer_license_from_rights(
        {"rights_description": "Creative Commons Attribution-ShareAlike 4.0"}
    )
    assert license_id == licenses.CC_BY_SA
    assert description == "Creative Commons Attribution-ShareAlike 4.0"


def test_infer_license_public_domain_from_restrictions():
    license_id, _ = infer_license_from_rights({"copyrightAndOtherRestrictions": "no"})
    assert license_id == licenses.PUBLIC_DOMAIN


def test_infer_license_none_when_unknown():
    assert infer_license_from_rights({}) == (None, None)


def test_extract_lifecycle_contributors_from_vcards():
    result = extract_lifecycle_contributors(
        {
            "contribute": [
                {
                    "role": {"value": "author"},
                    "entity": "BEGIN:VCARD\nFN:Ada Lovelace\nEND:VCARD",
                },
                {
                    "role": {"value": "publisher"},
                    "entity": "BEGIN:VCARD\nORG:Acme Ed\nEND:VCARD",
                },
            ]
        }
    )
    assert result == {"author": "Ada Lovelace", "provider": "Acme Ed"}


def test_metadata_dict_to_content_node_fields_full():
    fields = metadata_dict_to_content_node_fields(
        {
            "title": "Intro to Widgets",
            "description": "A short lesson.",
            "language": "en-US",
            "keyword": "widgets",
            "learningResourceType": "narrative text",
            "rights_description": "Creative Commons Attribution 4.0",
            "difficulty": "very easy",
            "contribute": {
                "role": {"value": "author"},
                "entity": "FN:Grace Hopper",
            },
        }
    )
    assert fields["title"] == "Intro to Widgets"
    assert fields["description"] == "A short lesson."
    assert fields["language"] == "en"
    assert fields["tags"] == ["widgets"]
    assert fields["learning_activities"] == [learning_activities.READ]
    assert fields["resource_types"] == [resource_type.TEXTBOOK]
    assert fields["learner_needs"] == [needs.FOR_BEGINNERS]
    assert fields["license"] == licenses.CC_BY
    assert fields["author"] == "Grace Hopper"


def test_metadata_dict_to_content_node_fields_empty():
    assert metadata_dict_to_content_node_fields({}) == {}


def test_multilingual_lom_fields_reduce_to_single_values():
    # LOM repeats a field per language, so the parser hands back lists (and lists
    # of lists for repeated elements). Node fields that must be strings take the
    # first value, and mapping lookups must not be handed an unhashable list.
    fields = metadata_dict_to_content_node_fields(
        {
            "title": ["Intro to Widgets", "Introducción a los Widgets"],
            "description": ["A short lesson.", "Una lección corta."],
            "language": ["en-US", "es"],
            "keyword": [["widgets", "gears"], "cogs"],
            "learningResourceType": [["narrative text"], "lecture"],
            "intendedEndUserRole": [["teacher"]],
            "rights_description": ["Creative Commons Attribution 4.0", "CC BY 4.0"],
        }
    )
    assert fields["title"] == "Intro to Widgets"
    assert fields["description"] == "A short lesson."
    assert fields["language"] == "en"
    assert fields["tags"] == ["widgets", "gears", "cogs"]
    assert fields["learning_activities"] == [
        learning_activities.READ,
        learning_activities.WATCH,
    ]
    assert resource_type.LESSON_PLAN in fields["resource_types"]
    assert fields["license"] == licenses.CC_BY
    assert fields["license_description"] == "Creative Commons Attribution 4.0"


def test_over_long_keywords_are_dropped():
    # LOM keywords are often whole phrases, and a tag over 30 characters fails
    # node validation — dropping it must not take the whole package down with it.
    fields = metadata_dict_to_content_node_fields(
        {"keyword": ["widgets", "Data (especially computer data)!"]}
    )
    assert fields["tags"] == ["widgets"]
