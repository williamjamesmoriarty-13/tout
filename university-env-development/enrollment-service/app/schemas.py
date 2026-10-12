from marshmallow import Schema, fields, validate


class EnrollmentCreateSchema(Schema):
    student_id = fields.Integer(strict=True, required=True, validate=validate.Range(min=1))
    course_id = fields.Integer(strict=True, required=True, validate=validate.Range(min=1))
