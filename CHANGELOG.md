# Changelog

## 1.0.0 (2026-11-18)


### Features

* (2.1) Background chat answers and pipeline inspector on dev ([#69](https://github.com/kthaisociety/pyrmit/issues/69)) ([34915da](https://github.com/kthaisociety/pyrmit/commit/34915da22d8f1cddb3bbc53effeacadf3874d94b))
* (2.2) Corpus-building commands run on dev ([#70](https://github.com/kthaisociety/pyrmit/issues/70)) ([ddea27e](https://github.com/kthaisociety/pyrmit/commit/ddea27e3825ecc3a126e1b38a72c284af585d331))
* (2.3) Chat and Database view search the local corpus on dev ([#71](https://github.com/kthaisociety/pyrmit/issues/71)) ([79375da](https://github.com/kthaisociety/pyrmit/commit/79375da6e3a051444df777477ba68c40661d3519))
* (2.5) Map pin and place card work on dev ([#72](https://github.com/kthaisociety/pyrmit/issues/72)) ([21ab4c1](https://github.com/kthaisociety/pyrmit/commit/21ab4c19d3a80d089b1713ad65ff2a8944acf230))
* (2.6) Pipeline view runs on dev ([#73](https://github.com/kthaisociety/pyrmit/issues/73)) ([bf11cfc](https://github.com/kthaisociety/pyrmit/commit/bf11cfc1e38d1bdad6d2c21e14aadbb3e85fef75))
* add MIT license ([45ad023](https://github.com/kthaisociety/pyrmit/commit/45ad0232b6f48c4aebff44d2ae42942e76cfdc6c))
* Answers in the question's language ([#78](https://github.com/kthaisociety/pyrmit/issues/78)) ([3c9d8ee](https://github.com/kthaisociety/pyrmit/commit/3c9d8ee66f6df24c8a1156d21b8a836df1d8b723))
* build and release pipeline for the backend and frontend images ([#42](https://github.com/kthaisociety/pyrmit/issues/42)) ([8790290](https://github.com/kthaisociety/pyrmit/commit/8790290a90b7bde7a4547a84b0a8bf68540dffc7))
* change to use vercel AI gateway for AI stuff ([3d0bc13](https://github.com/kthaisociety/pyrmit/commit/3d0bc130120020a9893173cdccf48a7324f35de2))
* chunking and pushing to db after embedding ([3cfac01](https://github.com/kthaisociety/pyrmit/commit/3cfac01f007406f79c6db63c94397f587a0c6e64))
* codebase-refactor ([f8d6466](https://github.com/kthaisociety/pyrmit/commit/f8d64666d43221670edacf1b1fa21043bbf280f9))
* Corpus documents and chunks carry the schema labels ([#107](https://github.com/kthaisociety/pyrmit/issues/107)) ([a4bc118](https://github.com/kthaisociety/pyrmit/commit/a4bc118440a339ef5a9eacf24ad0ee3bf16324ab))
* Corpus read from DATABASE_URL on the IT platform, plus a local copy of staging ([#110](https://github.com/kthaisociety/pyrmit/issues/110)) ([201b730](https://github.com/kthaisociety/pyrmit/commit/201b7303744ed0cd84a446b5200560afb3754bed))
* Correct logout ([e142e52](https://github.com/kthaisociety/pyrmit/commit/e142e522baea24cfba55d6800a5a87b81bd4cd3e))
* enhance authFetch to redirect to access gate on 401/403 errors ([ca2fa51](https://github.com/kthaisociety/pyrmit/commit/ca2fa5141290c144a24fa7ffc3676d8388215443))
* enhance CORS configuration and secure cookie handling ([0f7eb4a](https://github.com/kthaisociety/pyrmit/commit/0f7eb4a0c8afadf356ef124b678c8bd50cc890c8))
* fix deployment variables for frontend ([8269f84](https://github.com/kthaisociety/pyrmit/commit/8269f8424ff9de3a6ae3ab0147e7e2ee946ec09c))
* fix dev-access gate + remove nextjs middleware for auth protection ([1610647](https://github.com/kthaisociety/pyrmit/commit/16106470e46f059509eea5de964f46ad67bc9363))
* Neon ([14311fc](https://github.com/kthaisociety/pyrmit/commit/14311fc54495369a23e8363fea179db88dfde270))
* one shot fix auth ([7badaee](https://github.com/kthaisociety/pyrmit/commit/7badaee49e510f89a68b10af4e7fd19cad0278c7))
* one shot fix auth ([ed683b3](https://github.com/kthaisociety/pyrmit/commit/ed683b3dd5765ddfbfe4d9dc58ea21f33c4c9abe))
* Owners replace the corpus from the Database tab ([#115](https://github.com/kthaisociety/pyrmit/issues/115)) ([6e9dc9b](https://github.com/kthaisociety/pyrmit/commit/6e9dc9bcdbc98978a51384be5fe4a0f4e6a8194f))
* Page in Swedish or English ([#79](https://github.com/kthaisociety/pyrmit/issues/79)) ([8c9145f](https://github.com/kthaisociety/pyrmit/commit/8c9145f36f3735291a70d4b34649eff7213fae73))
* Pipeline view shows what a rebuild costs, and pg_store loads in parallel ([#111](https://github.com/kthaisociety/pyrmit/issues/111)) ([d1d5ced](https://github.com/kthaisociety/pyrmit/commit/d1d5ced041ea47d991f1ecf9c1a5ff44de066f20))
* query as yaml ([f0b7778](https://github.com/kthaisociety/pyrmit/commit/f0b77784f96b49ff4d853c262ebb5cc80a7a7b4f))
* Question embeddings run on the user's own OpenRouter key ([#118](https://github.com/kthaisociety/pyrmit/issues/118)) ([09bb87e](https://github.com/kthaisociety/pyrmit/commit/09bb87e7ae972c857f71f2f3ea3019c986b76269))
* setup frontend docker for deployment + migrate nextjs from 14-&gt;16 ([1cb082e](https://github.com/kthaisociety/pyrmit/commit/1cb082ee81733e052c0ca70a48c231f7e95608ce))
* sidebar chat history + auth ([d91b3cf](https://github.com/kthaisociety/pyrmit/commit/d91b3cfda61c859872e1ff2f98541995c80fdabd))
* Users enter their own OpenRouter key ([#109](https://github.com/kthaisociety/pyrmit/issues/109)) ([802b66c](https://github.com/kthaisociety/pyrmit/commit/802b66cf553676af275242b3165b99d781fd3cef))
* Users have a role (owner, developer, user) ([#113](https://github.com/kthaisociety/pyrmit/issues/113)) ([7e22ead](https://github.com/kthaisociety/pyrmit/commit/7e22ead19a7001f5034ad82893afc9327b9202cf))


### Bug Fixes

* Agent answers first, Jev checks claims fast, input stays open ([#105](https://github.com/kthaisociety/pyrmit/issues/105)) ([5b4d9a3](https://github.com/kthaisociety/pyrmit/commit/5b4d9a31b0254acdeb7c5ec5691d5006a93a7e41))
* Agent asks for missing facts instead of guessing ([#93](https://github.com/kthaisociety/pyrmit/issues/93)) ([9473b5f](https://github.com/kthaisociety/pyrmit/commit/9473b5fadbceb1449f0adf34eadb868b373d5f23))
* Backend crashes on startup, trafilatura missing from image ([#101](https://github.com/kthaisociety/pyrmit/issues/101)) ([1e072fc](https://github.com/kthaisociety/pyrmit/commit/1e072fc5be8c9e5cae0f796dd00b1b9227320f72))
* correction of year in license ([4cbd7bf](https://github.com/kthaisociety/pyrmit/commit/4cbd7bf4136e047eb56a62f304a66e78c99fd3e9))
* fix streaming ai repsonse, toolcalls and reasoning ([71417b0](https://github.com/kthaisociety/pyrmit/commit/71417b05eb087a11621b22fa14e515ff8c0251ec))
* Scanned PDFs highlight the cited passage ([#86](https://github.com/kthaisociety/pyrmit/issues/86)) ([c7a240e](https://github.com/kthaisociety/pyrmit/commit/c7a240e31e784463a0f1d12c0e239bbf17cbcacd))
* The chat says why it cannot answer instead of showing nothing ([#120](https://github.com/kthaisociety/pyrmit/issues/120)) ([0e5097b](https://github.com/kthaisociety/pyrmit/commit/0e5097b02fe00206d02ebe30d792f54f72c8785f))
* The chat stops pulling the view down while an answer streams ([#90](https://github.com/kthaisociety/pyrmit/issues/90)) ([8e4fee3](https://github.com/kthaisociety/pyrmit/commit/8e4fee3bcf19742468ec81fa6facad7bfd4c0706))
* The property lookup survives Uppsala's service failing every other call ([#88](https://github.com/kthaisociety/pyrmit/issues/88)) ([ee11ae8](https://github.com/kthaisociety/pyrmit/commit/ee11ae8af5b07f05311ec12389d2f0cd803c3738))
* The source panel underlines the supporting text ([#87](https://github.com/kthaisociety/pyrmit/issues/87)) ([7d832a2](https://github.com/kthaisociety/pyrmit/commit/7d832a2483ddc10e5b7c3747d24792c9d451a2b6))
* Unsupported claims are rewritten or flagged ([#85](https://github.com/kthaisociety/pyrmit/issues/85)) ([73e1213](https://github.com/kthaisociety/pyrmit/commit/73e1213deb503e136a6c4eedf0c1404009ac7f51))
