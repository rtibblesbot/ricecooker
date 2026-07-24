"""Map the raw LOM metadata dict :mod:`ricecooker.utils.imscp` extracts onto
le_utils content-node fields. Ported from ricecooker PR #468.
"""

import re

from le_utils.constants import licenses
from le_utils.constants.labels import learning_activities
from le_utils.constants.labels import needs
from le_utils.constants.labels import resource_type

from ricecooker.utils.youtube import get_language_with_alpha2_fallback

# LOM sections and the fields the parser lifts out of each. Keyed by the LOM
# ``<general>``/``<rights>``/``<educational>``/``<lifeCycle>`` element name.
imscp_metadata_keys = {
    "general": ["title", "description", "language", "keyword"],
    "rights": ["cost", "copyrightAndOtherRestrictions", "description"],
    "educational": [
        "interactivityType",
        "interactivityLevel",
        "learningResourceType",
        "intendedEndUserRole",
    ],
    "lifeCycle": ["contribute"],
}


# LOM educational learningResourceType -> (le_utils learning activity,
# educator-focused le_utils resource type). One table so the two vocabularies
# cannot drift apart as terms are added.
_LEARNING_RESOURCE_TYPE_MAPPINGS = {
    "exercise": (learning_activities.PRACTICE, resource_type.EXERCISE),
    "simulation": (learning_activities.EXPLORE, resource_type.ACTIVITY),
    "questionnaire": (learning_activities.PRACTICE, resource_type.ACTIVITY),
    "diagram": (learning_activities.EXPLORE, resource_type.MEDIA),
    "figure": (learning_activities.EXPLORE, resource_type.MEDIA),
    "graph": (learning_activities.EXPLORE, resource_type.MEDIA),
    "index": (learning_activities.READ, resource_type.GUIDE),
    "slide": (learning_activities.READ, resource_type.LESSON),
    "table": (learning_activities.READ, resource_type.TUTORIAL),
    "narrative text": (learning_activities.READ, resource_type.TEXTBOOK),
    "exam": (learning_activities.PRACTICE, resource_type.EXERCISE),
    "experiment": (learning_activities.EXPLORE, resource_type.ACTIVITY),
    "problem statement": (learning_activities.REFLECT, resource_type.ACTIVITY),
    "self assessment": (learning_activities.REFLECT, resource_type.ACTIVITY),
    "lecture": (learning_activities.WATCH, resource_type.LESSON),
}


def _ensure_list(value):
    """Normalize a value to a list: None -> [], str -> [str], other -> list."""
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    return list(value)


def map_scorm_to_le_utils_activities(metadata_dict):
    le_utils_activities = []

    # When the resource is not interactive, downgrade activities that imply
    # interactivity to a passive equivalent (simulation -> read, else watch).
    interactive_adjustments = {
        learning_activities.EXPLORE: (
            learning_activities.READ,
            learning_activities.WATCH,
        )
    }

    interactivity_type = metadata_dict.get("interactivityType")
    interactivity_level = metadata_dict.get("interactivityLevel")

    is_interactive = interactivity_type in [
        "active",
        "mixed",
    ] or interactivity_level in ["medium", "high"]

    learning_resource_types = _ensure_list(metadata_dict.get("learningResourceType"))

    for learning_resource_type in learning_resource_types:
        le_utils_type = SCORM_to_learning_activities_mappings.get(
            learning_resource_type
        )
        if not is_interactive and le_utils_type in interactive_adjustments:
            le_utils_type = (
                interactive_adjustments[le_utils_type][0]
                if learning_resource_type == "simulation"
                else interactive_adjustments[le_utils_type][1]
            )
        if activity and activity not in activities:
            activities.append(activity)

    return activities


# LOM intendedEndUserRole -> educator resource type, when the role is an educator.
SCORM_intended_role_to_resource_type_mapping = {
    "teacher": resource_type.LESSON_PLAN,
    "author": resource_type.GUIDE,
    "manager": resource_type.GUIDE,
}


def map_scorm_to_educator_resource_types(metadata_dict):
    educator_resource_types = []

    learning_resource_types = _ensure_list(metadata_dict.get("learningResourceType"))
    intended_roles = _ensure_list(metadata_dict.get("intendedEndUserRole"))

    for learning_resource_type in learning_resource_types:
        mapped_type = SCORM_to_resource_type_mappings.get(learning_resource_type)
        if mapped_type and mapped_type not in educator_resource_types:
            educator_resource_types.append(mapped_type)

    return types


def infer_beginner_level_from_difficulty(metadata_dict):
    beginner_difficulties = {"very easy", "easy"}

    difficulty = metadata_dict.get("difficulty")
    if difficulty in beginner_difficulties:
        return [needs.FOR_BEGINNERS]
    return []


def _vcard_field(vcard_text, field):
    """The value of VCARD ``field`` (``FN``, ``ORG``) in ``vcard_text``, or None."""
    match = re.search(r"^{}:(.+)$".format(field), vcard_text or "", re.MULTILINE)
    return match.group(1).strip() if match else None


# CC licence patterns, ordered most specific first to avoid partial matches.
_CC_LICENSE_PATTERNS = [
    ("Attribution-NonCommercial-ShareAlike", licenses.CC_BY_NC_SA),
    ("Attribution-NonCommercial-NoDerivs", licenses.CC_BY_NC_ND),
    ("Attribution-ShareAlike", licenses.CC_BY_SA),
    ("Attribution-NoDerivs", licenses.CC_BY_ND),
    ("Attribution-NonCommercial", licenses.CC_BY_NC),
    ("Attribution", licenses.CC_BY),
]


def infer_license_from_rights(metadata_dict):
    """Infer a ``(license_id, license_description)`` tuple from rights metadata.

    Either or both may be ``None``.
    """
    description = metadata_dict.get("rights_description")
    copyright_restrictions = metadata_dict.get("copyrightAndOtherRestrictions")

    if description:
        for pattern, license_id in _CC_LICENSE_PATTERNS:
            if pattern in description:
                return license_id, description

    if copyright_restrictions == "no":
        return licenses.PUBLIC_DOMAIN, description

    return None, description


# LOM contribute role -> (result field name, whether to prefer ORG over FN).
_ROLE_TO_FIELD = {
    "author": ("author", False),
    "publisher": ("provider", True),
    "content provider": ("copyright_holder", True),
}


def extract_lifecycle_contributors(metadata_dict):
    """Extract author/provider/copyright_holder from lifeCycle contribute data."""
    result = {}
    contribute = metadata_dict.get("contribute")
    if not contribute:
        return result

    if isinstance(contribute, dict):
        contribute = [contribute]

    for entry in contribute:
        role_value = entry.get("role", {})
        if isinstance(role_value, dict):
            role_value = role_value.get("value", "")
        entity = entry.get("entity", "")

        field_config = _ROLE_TO_FIELD.get(role_value)
        if not field_config:
            continue
        field_name, prefer_org = field_config
        name = (prefer_org and _vcard_field(entity, "ORG")) or _vcard_field(
            entity, "FN"
        )
        if name:
            result[field_name] = name

    return result


def _normalize_language(lang_code):
    """Normalize a language code, returning None if unrecognized."""
    language = get_language_with_alpha2_fallback(lang_code) if lang_code else None
    return language.code if language else None


def _normalize_keywords(keyword):
    """Normalize the keyword field to a list, or None if empty."""
    if not keyword:
        return None
    if isinstance(keyword, str):
        return [keyword]
    return keyword


def metadata_dict_to_content_node_fields(metadata_dict):
    """Convert a raw LOM metadata dict to ``ContentNodeMetadata`` fields.

    Maps title/description/language/keyword straight through (language
    normalized, keyword -> tags), educational fields to learning_activities /
    resource_types / learner_needs, rights to license / license_description, and
    lifeCycle contribute to author / provider / copyright_holder. Only non-empty
    values are returned.
    """
    result = {}

    if metadata_dict.get("title"):
        result["title"] = metadata_dict["title"]

    if metadata_dict.get("description"):
        result["description"] = metadata_dict["description"]

    language = _normalize_language(metadata_dict.get("language", ""))
    if language:
        result["language"] = language

    tags = _normalize_keywords(metadata_dict.get("keyword", []))
    if tags:
        result["tags"] = tags

    activities = map_scorm_to_le_utils_activities(metadata_dict)
    if activities:
        result["learning_activities"] = activities

    resource_types = map_scorm_to_educator_resource_types(metadata_dict)
    if resource_types:
        result["resource_types"] = resource_types

    learner_needs = infer_beginner_level_from_difficulty(metadata_dict)
    if learner_needs:
        result["learner_needs"] = learner_needs

    license_id, license_description = infer_license_from_rights(metadata_dict)
    fields = {
        # title/description/language are single-valued on a content node, but LOM
        # may supply one per language; take the first rather than handing node
        # validation a list it rejects.
        "title": _first_text(metadata_dict.get("title")),
        "description": _first_text(metadata_dict.get("description")),
        "language": _normalize_language(_first_text(metadata_dict.get("language"))),
        "tags": _normalize_keywords(metadata_dict.get("keyword", [])),
        "learning_activities": map_scorm_to_le_utils_activities(metadata_dict),
        "resource_types": map_scorm_to_educator_resource_types(metadata_dict),
        "learner_needs": infer_beginner_level_from_difficulty(metadata_dict),
        "license": license_id,
        "license_description": license_description,
        **extract_lifecycle_contributors(metadata_dict),
    }
    return {key: value for key, value in fields.items() if value}
