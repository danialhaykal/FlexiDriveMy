"""Run 2 fix batch 3 (D1, X2, A5) and Run 3 fix batch 5 (F-02): plain-English
wording for DRF's own validation messages - once, centrally, for every current
and future serializer.

DRF's defaults reach buyers and admins as they are: "A valid number is
required.", "This field is required.", 'Invalid pk "9" - object does not
exist.', "Ensure this value is greater than or equal to 12.", "The fields brand,
tenure_months, mileage_band must make a unique set.". plain_error_messages()
rewrites exactly those, and nothing else:

- It is keyed on the error CODE AND on DRF's (or Django's) own default sentence
  for that code (taken from the field and validator classes, not copied here).
  A code alone would be too broad (`invalid` is shared by dates, e-mail,
  booleans and more), and a message a serializer or validator wrote itself
  (already plain) never matches a default, so it is never touched.
- The new sentence names the field by its human label: the serializer's own
  label when the caller passes it (`labels`), otherwise the field key made
  readable ("tenure_months" -> "Tenure months", "max_dsr_percent" -> "Max DSR
  percent"). Non-field errors read "This value ...".
- It returns a new structure with the same keys, nesting and error codes, so
  field names and status codes stay exactly as they were.

apps.audit.runtime_errors.api_exception_handler applies it to every
ValidationError response (with the view's serializer labels when the view has
one); the bulk-import report, which builds its row errors by hand, calls it too.
"""

import re

from django.core import validators as django_validators
from rest_framework import serializers
from rest_framework.exceptions import ErrorDetail
from rest_framework.settings import api_settings
from rest_framework.validators import UniqueTogetherValidator

DIGITS_LIMIT_TEMPLATE = "That number is too large. Use at most {n} digits {where}."

# Short forms kept in capitals (or their usual case) when a field key is made readable.
_WORD_CASE = {
    "msrp": "MSRP", "dsr": "DSR", "ncd": "NCD", "gfv": "GFV", "hp": "HP", "kw": "kW", "cc": "cc", "km": "km",
    "url": "URL", "pdf": "PDF", "svg": "SVG", "ml": "ML", "csv": "CSV", "id": "ID", "pk": "ID", "voc": "VOC",
    "jpj": "JPJ", "rm": "RM", "mae": "MAE",
}
GENERIC_LABEL = "This value"


def readable_label(text):
    """'max_dsr_percent' or 'Max dsr percent' -> 'Max DSR percent'; short forms keep their case."""
    words = str(text).replace("_", " ").split()
    if not words:
        return GENERIC_LABEL
    fixed = [_WORD_CASE.get(word.lower(), word) for word in words]
    first = fixed[0]
    if first == words[0] and first[:1].islower():
        fixed[0] = first[:1].upper() + first[1:]
    return " ".join(fixed)


def _in_sentence(label):
    """The label inside a sentence: 'Vehicle' -> 'vehicle', but 'MSRP' stays 'MSRP'."""
    if label[:2].isupper() or label == GENERIC_LABEL:
        return label if label != GENERIC_LABEL else "value"
    return label[:1].lower() + label[1:]


def _regex_for(template):
    """A '... {max_digits} ...' (DRF) or '... %(limit_value)s ...' (Django) template as a regex
    capturing its placeholders."""
    text = re.sub(r"%\((\w+)\)[sd]", r"{\1}", str(template))
    pattern = re.escape(text)
    return re.compile("^" + re.sub(r"\\\{(\w+)\\\}", r"(?P<\1>.*?)", pattern) + "$", re.DOTALL)


def _plain_decimal_places(match, label):
    n = int(match.group("max_decimal_places"))
    return f"Please use at most {n} decimal place{'' if n == 1 else 's'}."


def _limit(value):
    """'12' -> '12', '0.01' -> '0.01', '15.00' -> '15'."""
    text = str(value).strip()
    if re.fullmatch(r"-?\d+\.0+", text):
        return text.split(".")[0]
    return text


def _joined(names):
    names = [_in_sentence(readable_label(name)) for name in names]
    return names[0] if len(names) == 1 else ", ".join(names[:-1]) + " and " + names[-1]


def _unique_set(match, label):
    return f"A record with this {_joined([n.strip() for n in match.group('field_names').split(',')])} already exists."


def _model_unique(match, label):
    model = match.group("model_name").strip()
    if not model[:1].islower():
        return None  # DRF's sentence uses the lower-case model name; a capitalised one was written by hand
    article = "An" if model[:1] in "aeiou" else "A"
    return f"{article} {model} with this {_in_sentence(readable_label(match.group('field_label')))} already exists."


_REQUIRED = lambda m, label: f"{label} is required."  # noqa: E731

# (code, DRF's / Django's default sentence for it, builder of the plain sentence from the match and the
# field's label). Order matters only where two defaults share a code; each sentence is distinct.
_RULES = [
    # numbers and choices (Run 2 fix batch 3)
    ("invalid", serializers.IntegerField.default_error_messages["invalid"], lambda m, label: "Please enter a whole number."),
    ("invalid", serializers.DecimalField.default_error_messages["invalid"], lambda m, label: "Please enter a valid number."),
    ("invalid", serializers.FloatField.default_error_messages["invalid"], lambda m, label: "Please enter a valid number."),
    (
        "max_whole_digits",
        serializers.DecimalField.default_error_messages["max_whole_digits"],
        lambda m, label: DIGITS_LIMIT_TEMPLATE.format(n=m.group("max_whole_digits"), where="before the decimal point"),
    ),
    (
        "max_digits",
        serializers.DecimalField.default_error_messages["max_digits"],
        lambda m, label: DIGITS_LIMIT_TEMPLATE.format(n=m.group("max_digits"), where="in total"),
    ),
    ("max_decimal_places", serializers.DecimalField.default_error_messages["max_decimal_places"], _plain_decimal_places),
    ("invalid_choice", serializers.ChoiceField.default_error_messages["invalid_choice"],
     lambda m, label: "Choose one of the available options."),
    # Run 3 fix batch 5 (F-02): the other templates seen on 93 of 101 request fields
    ("required", serializers.Field.default_error_messages["required"], _REQUIRED),
    ("null", serializers.Field.default_error_messages["null"], _REQUIRED),
    ("blank", serializers.CharField.default_error_messages["blank"], _REQUIRED),
    ("invalid", serializers.CharField.default_error_messages["invalid"], lambda m, label: f"{label} must be text."),
    ("max_length", serializers.CharField.default_error_messages["max_length"],
     lambda m, label: f"{label} can be at most {m.group('max_length')} characters long."),
    ("min_length", serializers.CharField.default_error_messages["min_length"],
     lambda m, label: f"{label} must be at least {m.group('min_length')} characters long."),
    ("min_value", serializers.IntegerField.default_error_messages["min_value"],
     lambda m, label: f"{label} must be {_limit(m.group('min_value'))} or more."),
    ("max_value", serializers.IntegerField.default_error_messages["max_value"],
     lambda m, label: f"{label} must be {_limit(m.group('max_value'))} or less."),
    ("min_value", django_validators.MinValueValidator.message,
     lambda m, label: f"{label} must be {_limit(m.group('limit_value'))} or more."),
    ("max_value", django_validators.MaxValueValidator.message,
     lambda m, label: f"{label} must be {_limit(m.group('limit_value'))} or less."),
    ("does_not_exist", serializers.PrimaryKeyRelatedField.default_error_messages["does_not_exist"],
     lambda m, label: f"The selected {_in_sentence(label)} does not exist or is no longer available."),
    ("incorrect_type", serializers.PrimaryKeyRelatedField.default_error_messages["incorrect_type"],
     lambda m, label: f"Choose a valid {_in_sentence(label)}."),
    ("invalid", serializers.URLField.default_error_messages["invalid"],
     lambda m, label: "Enter a valid web address, starting with http:// or https://."),
    ("invalid", serializers.EmailField.default_error_messages["invalid"],
     lambda m, label: "Enter a valid email address, for example name@example.com."),
    ("invalid", serializers.BooleanField.default_error_messages["invalid"], lambda m, label: f"{label} must be true or false."),
    ("invalid", serializers.DateField.default_error_messages["invalid"],
     lambda m, label: "Enter a date in the format YYYY-MM-DD."),
    ("invalid", serializers.Serializer.default_error_messages["invalid"],
     lambda m, label: f"{label} is not in the expected format."),
    ("not_a_list", serializers.ListField.default_error_messages["not_a_list"], lambda m, label: f"{label} must be a list."),
    ("not_a_list", serializers.ManyRelatedField.default_error_messages["not_a_list"],
     lambda m, label: f"{label} must be a list."),
    ("empty", serializers.ManyRelatedField.default_error_messages["empty"],
     lambda m, label: "Choose at least one option."),
    ("unique", UniqueTogetherValidator.message, _unique_set),
    # Django's model-unique sentence ("brand with this name already exists.") that ModelSerializer reuses
    ("unique", "{model_name} with this {field_label} already exists.", _model_unique),
]
_COMPILED = [(code, _regex_for(template), build) for code, template, build in _RULES]


def _plain_message(detail, label):
    code = getattr(detail, "code", None)
    if code is None:
        return detail
    text = str(detail)
    for rule_code, regex, build in _COMPILED:
        if code != rule_code:
            continue
        match = regex.match(text)
        if match:
            plain = build(match, label)
            return detail if plain is None else ErrorDetail(plain, code=code)
    return detail


def _label_for(key, labels):
    if key is None or isinstance(key, int) or key in (api_settings.NON_FIELD_ERRORS_KEY, "detail"):
        return GENERIC_LABEL
    if labels and labels.get(key):
        return readable_label(labels[key])
    return readable_label(key)


def plain_error_messages(data, labels=None, _label=GENERIC_LABEL):
    """`data` (a DRF error structure: dicts, lists and ErrorDetail strings) with
    DRF's default sentences replaced by plain ones that name the field;
    everything else is returned unchanged. `labels` ({field key: label}) applies
    to the top-level keys; nested keys are made readable from the key."""
    if isinstance(data, dict):
        return {key: plain_error_messages(value, _label=_label_for(key, labels)) for key, value in data.items()}
    if isinstance(data, (list, tuple)):
        return [plain_error_messages(item, _label=_label) for item in data]
    if isinstance(data, ErrorDetail):
        return _plain_message(data, _label)
    return data


def serializer_labels(serializer):
    """{field name: label} for a serializer instance or class; {} if it can't be built."""
    try:
        instance = serializer() if isinstance(serializer, type) else serializer
        return {name: field.label for name, field in instance.fields.items() if field.label}
    except Exception:  # noqa: BLE001 - labels are a nicety; never break an error response
        return {}


def labels_for_view(view):
    """The labels of the serializer a (generic) view uses, or {}."""
    if view is None:
        return {}
    try:
        serializer_class = view.get_serializer_class() if hasattr(view, "get_serializer_class") else None
    except Exception:  # noqa: BLE001 - e.g. an APIView without serializer_class
        serializer_class = None
    serializer_class = serializer_class or getattr(view, "serializer_class", None)
    return serializer_labels(serializer_class) if serializer_class else {}
