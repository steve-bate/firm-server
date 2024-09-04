# FIRM Server

This is a server demonstration implemented using the [FIRM](https://github.com/steve-bate/firm-server) (Federated Information Resource Manager) library.

## Current Features

* Built on [FIRM](https://github.com/steve-bate/firm-server)
  * Multi-actor
  * Multi-tenant
  * See [FIRM](https://github.com/steve-bate/firm-server) documentation for more information.
* File-based storage (JSON)
  * Partitioned storage
    * Remote cache, separate from tenant documents
    * Private storage
* Linked Data Support (using [firm-ld](https://github/steve-bate/firm-ld) library)
    - RDF Graph Storage
    - SPARQL endpoint
    - Full-Text Search on RDF data
* Uses [Starlette](https://www.starlette.io/) and [uvicorn](https://www.uvicorn.org/)
* Allows per-tenant web customization

## Future Work

* Integration testing with [activitypub-testsuite](https://github.com/steve-bate/activitypub-testsuite) (and/or [feditest](https://feditest.org/))
* Experiment with other storage strategies
* Improve tenant "theming"
* Explore which parts of the server can be further abstracted
