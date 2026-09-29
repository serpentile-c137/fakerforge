"""Base class for FakerForge domain providers."""

from faker.providers import BaseProvider


class ForgeProvider(BaseProvider):
    """Base class for custom domain providers.

    Subclass this and add public methods. Register the subclass with
    :meth:`fakerforge.FakerForge.add_provider`. Registered methods are then
    available on the ``FakerForge`` instance through Faker's provider lookup.

    This class does not copy or replace Faker providers. It is a subclass of
    :class:`faker.providers.BaseProvider`, so provider helpers such as
    ``random_element`` and ``numerify`` remain available.
    """
