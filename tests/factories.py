from __future__ import annotations

import factory

from app.core.security import hash_password
from app.models import User


class UserFactory(factory.Factory):
    class Meta:
        model = User

    email = factory.Sequence(lambda n: f"user{n}@example.com")
    hashed_password = factory.LazyFunction(lambda: hash_password("password123"))
    is_verified = True
    remnawave_uuid = factory.Sequence(lambda n: f"remna-{n}")
    traffic_limit_bytes = 107374182400

