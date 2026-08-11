# Contributing To MePhC

MePhC is the reusable layer shared by the lattice projects. Keep geometry
parameters and project-specific sampling policies in the consuming repository.

Before committing a public API change, run the import and low-resolution smoke
checks in the README using the `mp` environment. A change request from the web
audit workflow should identify the target file, public API impact, coordinate
convention, and verification command.

Generated records and images are not part of this repository. Keep them in the
consuming project's local archive and publish only lightweight metadata there.
