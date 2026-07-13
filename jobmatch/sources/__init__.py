"""Job-board source adapters."""

from .arbeitnow import ArbeitnowSource
from .jobicy import JobicySource
from .kariera import KarieraSource
from .profesia import ProfesiaSource
from .remoteok import RemoteOkSource
from .remotive import RemotiveSource

SOURCES = {
    source.name: source
    for source in (
        ProfesiaSource(),
        KarieraSource(),
        RemoteOkSource(),
        RemotiveSource(),
        JobicySource(),
        ArbeitnowSource(),
    )
}


def get_enabled(names):
    return [SOURCES[n] for n in names if n in SOURCES]
