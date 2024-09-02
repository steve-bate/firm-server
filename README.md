# FIRM Server

This is a server demonstration implemented using the [FIRM](https://github.com/steve-bate/firm-server) (Federated Information Resource Manager) library.

## Current Features

* Based on FIRM
  * Multi-actor
  * Multi-tenant
  * See [FIRM](https://github.com/steve-bate/firm-server) documentation for more information.
* File-based storage (JSON)
* Partitioned storage
  * Remote cache, separate from tenant documents
  * Private storage
* Uses [Starlette](https://www.starlette.io/) and [uvicorn](https://www.uvicorn.org/)
* Allows per-tenant web customization

## Road Map

- Version 0.2.0
  - Extended command line interface
  - Integration testing with [activitypub-testsuite](https://github.com/steve-bate/activitypub-testsuite) (and/or [feditest](https://feditest.org/))

## Future Work

* Experiment with other storage strategies
* Improve tenant "theming"
* Explore which parts of the server can be further abstracted
