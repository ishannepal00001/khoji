"""Site modules: the `Site` base class and the websites khoji supports out of the box."""

# `base` must come first: the chat layer that `whatsapp` builds on imports `Site` from it.
from .base import Site
from .whatsapp import WhatsApp

__all__ = ["Site", "WhatsApp"]
