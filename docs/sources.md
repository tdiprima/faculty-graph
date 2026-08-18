# Data Sources

API documentation and access notes for each publication source.

## ORCID

- **Public API base:** `https://pub.orcid.org/v3.0/`
- **Search endpoint:** `GET /v3.0/search/?q=...`
- **Record endpoint:** `GET /v3.0/{orcid-id}/works`
- **Auth:** Public API requires no credentials for read access. Rate-limited.
- **Docs:** https://info.orcid.org/documentation/api-tutorials/
- **Rate limits:** Public API allows ~24 requests/second for unauthenticated, higher with client credentials.
- **Response format:** XML by default, JSON with `Accept: application/json` header.

## PubMed (Future)

- **E-utilities base:** `https://eutils.ncbi.nlm.nih.gov/entrez/eutils/`
- **Search:** `esearch.fcgi?db=pubmed&term=...`
- **Fetch:** `efetch.fcgi?db=pubmed&id=...`
- **Docs:** https://www.ncbi.nlm.nih.gov/books/NBK25500/
- **API key:** Optional but recommended. Set `NCBI_API_KEY` env var.

## OpenAlex (Future)

- **Base:** `https://api.openalex.org/`
- **Works by author:** `GET /authors/{orcid}` or `GET /works?filter=author.orcid:{orcid}`
- **Docs:** https://docs.openalex.org/
- **Auth:** Free, no key needed. Polite pool with `mailto` parameter.
