"""Map the raw LOM metadata dict :mod:`ricecooker.utils.imscp` extracts onto
le_utils content-node fields. Ported from ricecooker PR #468.
"""

import logging
import re

from le_utils.constants import licenses
from le_utils.constants.labels import learning_activities
from le_utils.constants.labels import needs
from le_utils.constants.labels import resource_type

from ricecooker.utils.youtube import get_language_with_alpha2_fallback

LOGGER = logging.getLogger(__name__)

# Tags longer than this are rejected by node validation (``Node._validate``), and
# LOM keywords are routinely whole phrases, so over-long ones are dropped rather
# than allowed to fail the whole channel.
MAX_TAG_LENGTH = 30


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


def _text_list(value):
    """Flatten a LOM field (a string, a list, or a list of lists) to its text values.

    Non-text entries are dropped: an empty LOM element parses to ``None``, and a
    repeated element parses to a nested list.
    """
    if isinstance(value, str):
        return [value]
    if not isinstance(value, (list, tuple)):
        return []
    texts = []
    for item in value:
        if isinstance(item, str):
            texts.append(item)
        elif isinstance(item, (list, tuple)):
            texts.extend(t for t in item if isinstance(t, str))
    return texts


def _first_text(value):
    """The first non-blank text value of a LOM field, or None when it has none."""
    return next((t for t in _text_list(value) if t.strip()), None)


def map_scorm_to_le_utils_activities(metadata_dict):
    interactivity_type = _first_text(metadata_dict.get("interactivityType"))
    interactivity_level = _first_text(metadata_dict.get("interactivityLevel"))
    is_interactive = interactivity_type in (
        "active",
        "mixed",
    ) or interactivity_level in ("medium", "high")

    activities = []
    for lrt in _text_list(metadata_dict.get("learningResourceType")):
        mapping = _LEARNING_RESOURCE_TYPE_MAPPINGS.get(lrt)
        activity = mapping[0] if mapping else None
        # A non-interactive resource cannot be explored: read a simulation of
        # one, watch the rest.
        if activity == learning_activities.EXPLORE and not is_interactive:
            activity = (
                learning_activities.READ
                if lrt == "simulation"
                else learning_activities.WATCH
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
    lrt_types = {
        lrt: mapping[1] for lrt, mapping in _LEARNING_RESOURCE_TYPE_MAPPINGS.items()
    }
    types = []
    for key, mapping in (
        ("learningResourceType", lrt_types),
        ("intendedEndUserRole", SCORM_intended_role_to_resource_type_mapping),
    ):
        for text in _text_list(metadata_dict.get(key)):
            mapped = mapping.get(text)
            if mapped and mapped not in types:
                types.append(mapped)

    return types


def infer_beginner_level_from_difficulty(metadata_dict):
    if _first_text(metadata_dict.get("difficulty")) in ("very easy", "easy"):
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
    description = _first_text(metadata_dict.get("rights_description"))
    copyright_restrictions = _first_text(
        metadata_dict.get("copyrightAndOtherRestrictions")
    )

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
        role_value = _first_text(role_value)
        entity = _first_text(entry.get("entity")) or ""

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
    """Normalize the keyword field to a list of usable tags, or None if empty."""
    tags = []
    for keyword_text in _text_list(keyword):
        if not keyword_text:
            continue
        if len(keyword_text) > MAX_TAG_LENGTH:
            LOGGER.warning(
                "SCORM: dropping keyword longer than %s characters: %s",
                MAX_TAG_LENGTH,
                keyword_text,
            )
        else:
            tags.append(keyword_text)
    return tags or None


def _drop_unattributable_license(fields):
    """Drop an inferred license that requires a copyright holder LOM did not name.

    Applying it would fail node validation and take the whole channel down, so the
    node keeps whatever license the chef supplied.
    """
    # Imported here: ricecooker.classes imports the pipeline, which imports this module.
    from ricecooker.classes.licenses import get_license

    license_id = fields.get("license")
    if not license_id or fields.get("copyright_holder"):
        return
    if get_license(license_id).require_copyright_holder:
        LOGGER.warning(
            "SCORM: ignoring inferred %s license, no copyright holder was named",
            license_id,
        )
        del fields["license"]


def metadata_dict_to_content_node_fields(metadata_dict):
    """Convert a raw LOM metadata dict to ``ContentNodeMetadata`` fields, dropping empties."""
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
    fields = {key: value for key, value in fields.items() if value}
    _drop_unattributable_license(fields)
    return fields
