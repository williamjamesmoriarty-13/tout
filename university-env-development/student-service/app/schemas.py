from marshmallow import Schema, fields, validate, ValidationError


def not_blank(value: str) -> None:
    if not value.strip():
        raise ValidationError("Ce champ ne peut pas être uniquement composé d'espaces.")


class StudentCreateSchema(Schema):
    first_name = fields.String(
        required=True, validate=[validate.Length(min=1, max=80), not_blank]
    )
    last_name = fields.String(
        required=True, validate=[validate.Length(min=1, max=80), not_blank]
    )
    email = fields.Email(required=True, validate=validate.Length(max=120))


class StudentUpdateSchema(Schema):
    first_name = fields.String(validate=[validate.Length(min=1, max=80), not_blank])
    last_name = fields.String(validate=[validate.Length(min=1, max=80), not_blank])
    email = fields.Email(validate=validate.Length(max=120))
