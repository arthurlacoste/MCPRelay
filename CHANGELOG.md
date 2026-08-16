# Changelog

## [0.1.30](https://github.com/spelcc/gate/compare/v0.1.29...v0.1.30) (2026-08-16)


### Added

* add configurable MCP proxy aggregation ([d2c0d3d](https://github.com/spelcc/gate/commit/d2c0d3dddb44ffbb9af8691f9df348010c5cc580))
* add configurable MCP proxy aggregation ([38d77c9](https://github.com/spelcc/gate/commit/38d77c9e7931f1c43963f53e922b09ebdeb0b0e3))
* add configurable preprompt and hard limits for deepseek agent ([71b0e96](https://github.com/spelcc/gate/commit/71b0e969bea2f6ec6ecd0ad16bb0374fa0fedc34))
* add daemon log monitor ([#36](https://github.com/spelcc/gate/issues/36)) ([89c8f51](https://github.com/spelcc/gate/commit/89c8f5183a0cdb9ff57ed8e1b4bf5ccf54033608))
* add discover-first MCP tool exposure ([#66](https://github.com/spelcc/gate/issues/66)) ([06ba0e3](https://github.com/spelcc/gate/commit/06ba0e3374ebc988b88a59d2398e164b93d8f53b))
* add MCP auto-discovery and hot reload ([#27](https://github.com/spelcc/gate/issues/27)) ([2bbe9b3](https://github.com/spelcc/gate/commit/2bbe9b38ca349aefa0af58849ee46dd075c77617))
* add optional ChatGPT startup browser assist ([282e1ba](https://github.com/spelcc/gate/commit/282e1ba8fe52e233ad43c79080500f493bda3a85))
* add realtime call monitor ([#29](https://github.com/spelcc/gate/issues/29)) ([1c7d4c7](https://github.com/spelcc/gate/commit/1c7d4c7180d70501e0e4ae65db06ba0cda5fede0))
* add settings.yaml support and tool config ([549b5e8](https://github.com/spelcc/gate/commit/549b5e861ce7085ec2e9cd86425d5e74b2269ee3))
* expand realtime call details ([#53](https://github.com/spelcc/gate/issues/53)) ([ff691c7](https://github.com/spelcc/gate/commit/ff691c7f3ca0c70c44b79b90a2b5763912b5acb2))
* monitor all Gate realtime activity ([#69](https://github.com/spelcc/gate/issues/69)) ([b41ec34](https://github.com/spelcc/gate/commit/b41ec34187cbab128c9ad7ee223a7c4126267e9a))
* **rt:** add realtime call trajectory UI ([#72](https://github.com/spelcc/gate/issues/72)) ([d3cfd01](https://github.com/spelcc/gate/commit/d3cfd013d07c44e17078992bfc8b2f735599b2b2))
* **safety:** add pluggable command guards ([fcdce47](https://github.com/spelcc/gate/commit/fcdce478068cb1a7a25767891fa71662c952717a))
* support prerelease and explicit version updates ([#35](https://github.com/spelcc/gate/issues/35)) ([c8647c2](https://github.com/spelcc/gate/commit/c8647c2dc4115e05436e24802ab962cb17a4b8e4))


### Fixed

* align alpha changelog with release workflow ([5810b6d](https://github.com/spelcc/gate/commit/5810b6d1627bad9097e3393c4cd73aecd404dd15))
* align v0.1.19 changelog with release workflow ([2478f47](https://github.com/spelcc/gate/commit/2478f47881e69ac85ea4c4179280c1aa5002afa8))
* avoid duplicate realtime log reader ([#54](https://github.com/spelcc/gate/issues/54)) ([92922bf](https://github.com/spelcc/gate/commit/92922bf8eb1e73339c53114092ef27fccc4c4d5b))
* **ci:** install pytest for test workflow ([17c2bf3](https://github.com/spelcc/gate/commit/17c2bf324aa47165bd4305ed9fea5354685f4149))
* configure filesystem roots from environment ([#3](https://github.com/spelcc/gate/issues/3)) ([f36acd4](https://github.com/spelcc/gate/commit/f36acd40b2fb54765a09f6d6368737aeac72a09f))
* convert async def tools to def to unblock the event loop ([#6](https://github.com/spelcc/gate/issues/6)) ([d5252fb](https://github.com/spelcc/gate/commit/d5252fb19256b880efa91648cae9fe3c320987f2))
* handle Python version, SSL, and ngrok web_allow_hosts edge cases ([7a723cc](https://github.com/spelcc/gate/commit/7a723cc2db6db43d5e437fce838d2fb076439045))
* handle Python version, SSL, and ngrok web_allow_hosts edge cases ([813204f](https://github.com/spelcc/gate/commit/813204fedfa2bbb89e44be686bded46aa2294010))
* **installer:** support Alpine Linux ([b8e053d](https://github.com/spelcc/gate/commit/b8e053dc5680a15b78142d86efc2c94aa0ad66f5))
* **installer:** support Alpine Linux ([521a6ff](https://github.com/spelcc/gate/commit/521a6ff5ab65b18dcd34efb1feeb4136c4f9e49a))
* keep MCP tool catalog stable by default ([#63](https://github.com/spelcc/gate/issues/63)) ([bfb477d](https://github.com/spelcc/gate/commit/bfb477da1d114b278dc91f74c8acaa38829ad820))
* parse Release Please changelog headings ([#68](https://github.com/spelcc/gate/issues/68)) ([55cec7a](https://github.com/spelcc/gate/commit/55cec7a0b72df8dc5212c650d2e513ad90b8d458))
* probe gateway health on the resolved target ([#31](https://github.com/spelcc/gate/issues/31)) ([8677c4d](https://github.com/spelcc/gate/commit/8677c4ddd61a89a084491a502817a9a5240f4ff1))
* publish RFC 8414 OAuth metadata for issuer paths ([#52](https://github.com/spelcc/gate/issues/52)) ([91136ae](https://github.com/spelcc/gate/commit/91136aef7ddd04ddd297e940f77019794949d35f))
* reset Release Please state to v0.1.19 ([#47](https://github.com/spelcc/gate/issues/47)) ([b8ad057](https://github.com/spelcc/gate/commit/b8ad0577497205449e7b9c635e09f7062b4f9d73))
* route ngrok to the production gateway ([#30](https://github.com/spelcc/gate/issues/30)) ([acd8653](https://github.com/spelcc/gate/commit/acd8653ca87dd87cea67357526bc1877fefba65d))
* stabilize realtime terminal rendering ([#59](https://github.com/spelcc/gate/issues/59)) ([5c55c7c](https://github.com/spelcc/gate/commit/5c55c7c45d04e4c5cf62901a7f99e4d816eac7a7))
* test draft releases from commit SHA ([#51](https://github.com/spelcc/gate/issues/51)) ([b3491d6](https://github.com/spelcc/gate/commit/b3491d66b61bde51dad81fc3405447fa2c6666fa))
* **test:** update venv bootstrap assertion for find_compatible_python ([dfad906](https://github.com/spelcc/gate/commit/dfad906f45fa5f3c4810cc4881991ae5ea9de023))
* **test:** use active Python in onboarding sandbox ([516bc0e](https://github.com/spelcc/gate/commit/516bc0ed0097a6ed567d50e0b5d8f1ab1b125697))
* use venv interpreter for startup checks ([97ad220](https://github.com/spelcc/gate/commit/97ad2205aa68f876879e92614226c452eeee021a))


### Documentation

* Add DeepSeek Agent preprompt and refine .gitignore ([6510132](https://github.com/spelcc/gate/commit/6510132c388ba95fc519abee27fbeeae402a6a66))
* add VISION banner ([8ba925e](https://github.com/spelcc/gate/commit/8ba925eacb560889ce6bc62b47da795e2c33e23f))
* Update README: add features, remove userscript, update license ([608efeb](https://github.com/spelcc/gate/commit/608efebd6944e348e73b373697a7c147625c9d0f))


### Tests

* isolate Gate runtime environment ([#61](https://github.com/spelcc/gate/issues/61)) ([60226e4](https://github.com/spelcc/gate/commit/60226e4481a622dc60bb0e094405eca0e636b169))
* remove queue and skill catalog flakes ([61bd35b](https://github.com/spelcc/gate/commit/61bd35b55da4845e619f8a15dd08ed208513cf4c))


### Continuous Integration

* add Release Please automation ([#42](https://github.com/spelcc/gate/issues/42)) ([ed34f17](https://github.com/spelcc/gate/commit/ed34f17c9e120747b8d0d7a4081e29a1371352a6))
* allow manual release workflow runs ([#55](https://github.com/spelcc/gate/issues/55)) ([7b073c2](https://github.com/spelcc/gate/commit/7b073c2aab466ffb37bc352204249a79d3c5fb3d))


### Maintenance

* enforce pull request structure ([#33](https://github.com/spelcc/gate/issues/33)) ([3555090](https://github.com/spelcc/gate/commit/355509073789eb989b77dc3f2c263f4a21f2d15a))
* **main:** release 0.1.20 ([#48](https://github.com/spelcc/gate/issues/48)) ([966184c](https://github.com/spelcc/gate/commit/966184c38b6eb8b5214b206429c40459bb3d27f0))
* **main:** release 0.1.21 ([#49](https://github.com/spelcc/gate/issues/49)) ([4b67ca3](https://github.com/spelcc/gate/commit/4b67ca333ba95248611c91ba8d346f7b79d54f97))
* **main:** release 0.1.22 ([#56](https://github.com/spelcc/gate/issues/56)) ([5d6555c](https://github.com/spelcc/gate/commit/5d6555c656de9e5ba3f5eb9f4e94e4a027256e30))
* **main:** release 0.1.23 ([#57](https://github.com/spelcc/gate/issues/57)) ([3710985](https://github.com/spelcc/gate/commit/37109858f1966f62c3885a7713db07f8118e3e95))
* **main:** release 0.1.24 ([#60](https://github.com/spelcc/gate/issues/60)) ([0b35281](https://github.com/spelcc/gate/commit/0b352810f2f1106a1ebceefc2ce08b8bc3576478))
* **main:** release 0.1.25 ([#64](https://github.com/spelcc/gate/issues/64)) ([4f6d12a](https://github.com/spelcc/gate/commit/4f6d12a26dff9188af67e91d9e908746d6cce35c))
* **main:** release 0.1.26 ([#65](https://github.com/spelcc/gate/issues/65)) ([f65eb2c](https://github.com/spelcc/gate/commit/f65eb2c00115e3e89012fba091f4e321d1d190ce))
* **main:** release 0.1.27 ([#67](https://github.com/spelcc/gate/issues/67)) ([a865397](https://github.com/spelcc/gate/commit/a865397e1214c9d61c17b76ecccd8f6fdec3d711))
* **main:** release 0.1.28 ([#70](https://github.com/spelcc/gate/issues/70)) ([c564ada](https://github.com/spelcc/gate/commit/c564adad602332f51c36aa508be7f6996fb3a303))
* **main:** release 0.1.29 ([#73](https://github.com/spelcc/gate/issues/73)) ([4dda094](https://github.com/spelcc/gate/commit/4dda094bcfa8401eb6be2d1797e1b26c86cf8c1f))
* **main:** release Gate 0.1.20 ([#44](https://github.com/spelcc/gate/issues/44)) ([c753f60](https://github.com/spelcc/gate/commit/c753f60b9d75eb05c88aa17cdaa2c163e5da8af1))
* **main:** release gate 0.2.0 ([#43](https://github.com/spelcc/gate/issues/43)) ([36db61b](https://github.com/spelcc/gate/commit/36db61bfe392db686a94908268ad8f40b0f7abdf))
* release 0.1.19-alpha ([41ab5d1](https://github.com/spelcc/gate/commit/41ab5d10847c7f15e319d5f7f50507949bac6f69))
* **release:** prepare v0.1.13 ([152aaca](https://github.com/spelcc/gate/commit/152aacadf1c86294da0fa3af8abcae49f5136508))
* **release:** prepare v0.1.14 ([0e60b29](https://github.com/spelcc/gate/commit/0e60b2998c6dcafee128bbc37bbba0323b1a4d32))
* **release:** prepare v0.1.18 ([56114c9](https://github.com/spelcc/gate/commit/56114c9b1c8d2a0b2fccdf225c1dc557de0443f2))
* **release:** prepare v0.1.19 ([148f679](https://github.com/spelcc/gate/commit/148f679ce34e5241bc5486889b37892f8b8859db))

## [0.1.29](https://github.com/spelcc/gate/compare/v0.1.28...v0.1.29) (2026-08-16)


### Added

* **rt:** add realtime call trajectory UI ([#72](https://github.com/spelcc/gate/issues/72)) ([d3cfd01](https://github.com/spelcc/gate/commit/d3cfd013d07c44e17078992bfc8b2f735599b2b2))

## [0.1.28](https://github.com/spelcc/gate/compare/v0.1.27...v0.1.28) (2026-08-16)


### Added

* add configurable MCP proxy aggregation ([d2c0d3d](https://github.com/spelcc/gate/commit/d2c0d3dddb44ffbb9af8691f9df348010c5cc580))
* add configurable MCP proxy aggregation ([38d77c9](https://github.com/spelcc/gate/commit/38d77c9e7931f1c43963f53e922b09ebdeb0b0e3))
* add configurable preprompt and hard limits for deepseek agent ([71b0e96](https://github.com/spelcc/gate/commit/71b0e969bea2f6ec6ecd0ad16bb0374fa0fedc34))
* add daemon log monitor ([#36](https://github.com/spelcc/gate/issues/36)) ([89c8f51](https://github.com/spelcc/gate/commit/89c8f5183a0cdb9ff57ed8e1b4bf5ccf54033608))
* add discover-first MCP tool exposure ([#66](https://github.com/spelcc/gate/issues/66)) ([06ba0e3](https://github.com/spelcc/gate/commit/06ba0e3374ebc988b88a59d2398e164b93d8f53b))
* add MCP auto-discovery and hot reload ([#27](https://github.com/spelcc/gate/issues/27)) ([2bbe9b3](https://github.com/spelcc/gate/commit/2bbe9b38ca349aefa0af58849ee46dd075c77617))
* add optional ChatGPT startup browser assist ([282e1ba](https://github.com/spelcc/gate/commit/282e1ba8fe52e233ad43c79080500f493bda3a85))
* add realtime call monitor ([#29](https://github.com/spelcc/gate/issues/29)) ([1c7d4c7](https://github.com/spelcc/gate/commit/1c7d4c7180d70501e0e4ae65db06ba0cda5fede0))
* add settings.yaml support and tool config ([549b5e8](https://github.com/spelcc/gate/commit/549b5e861ce7085ec2e9cd86425d5e74b2269ee3))
* expand realtime call details ([#53](https://github.com/spelcc/gate/issues/53)) ([ff691c7](https://github.com/spelcc/gate/commit/ff691c7f3ca0c70c44b79b90a2b5763912b5acb2))
* **safety:** add pluggable command guards ([fcdce47](https://github.com/spelcc/gate/commit/fcdce478068cb1a7a25767891fa71662c952717a))
* support prerelease and explicit version updates ([#35](https://github.com/spelcc/gate/issues/35)) ([c8647c2](https://github.com/spelcc/gate/commit/c8647c2dc4115e05436e24802ab962cb17a4b8e4))


### Fixed

* align alpha changelog with release workflow ([5810b6d](https://github.com/spelcc/gate/commit/5810b6d1627bad9097e3393c4cd73aecd404dd15))
* align v0.1.19 changelog with release workflow ([2478f47](https://github.com/spelcc/gate/commit/2478f47881e69ac85ea4c4179280c1aa5002afa8))
* avoid duplicate realtime log reader ([#54](https://github.com/spelcc/gate/issues/54)) ([92922bf](https://github.com/spelcc/gate/commit/92922bf8eb1e73339c53114092ef27fccc4c4d5b))
* **ci:** install pytest for test workflow ([17c2bf3](https://github.com/spelcc/gate/commit/17c2bf324aa47165bd4305ed9fea5354685f4149))
* configure filesystem roots from environment ([#3](https://github.com/spelcc/gate/issues/3)) ([f36acd4](https://github.com/spelcc/gate/commit/f36acd40b2fb54765a09f6d6368737aeac72a09f))
* convert async def tools to def to unblock the event loop ([#6](https://github.com/spelcc/gate/issues/6)) ([d5252fb](https://github.com/spelcc/gate/commit/d5252fb19256b880efa91648cae9fe3c320987f2))
* handle Python version, SSL, and ngrok web_allow_hosts edge cases ([7a723cc](https://github.com/spelcc/gate/commit/7a723cc2db6db43d5e437fce838d2fb076439045))
* handle Python version, SSL, and ngrok web_allow_hosts edge cases ([813204f](https://github.com/spelcc/gate/commit/813204fedfa2bbb89e44be686bded46aa2294010))
* **installer:** support Alpine Linux ([b8e053d](https://github.com/spelcc/gate/commit/b8e053dc5680a15b78142d86efc2c94aa0ad66f5))
* **installer:** support Alpine Linux ([521a6ff](https://github.com/spelcc/gate/commit/521a6ff5ab65b18dcd34efb1feeb4136c4f9e49a))
* keep MCP tool catalog stable by default ([#63](https://github.com/spelcc/gate/issues/63)) ([bfb477d](https://github.com/spelcc/gate/commit/bfb477da1d114b278dc91f74c8acaa38829ad820))
* parse Release Please changelog headings ([#68](https://github.com/spelcc/gate/issues/68)) ([55cec7a](https://github.com/spelcc/gate/commit/55cec7a0b72df8dc5212c650d2e513ad90b8d458))
* probe gateway health on the resolved target ([#31](https://github.com/spelcc/gate/issues/31)) ([8677c4d](https://github.com/spelcc/gate/commit/8677c4ddd61a89a084491a502817a9a5240f4ff1))
* publish RFC 8414 OAuth metadata for issuer paths ([#52](https://github.com/spelcc/gate/issues/52)) ([91136ae](https://github.com/spelcc/gate/commit/91136aef7ddd04ddd297e940f77019794949d35f))
* reset Release Please state to v0.1.19 ([#47](https://github.com/spelcc/gate/issues/47)) ([b8ad057](https://github.com/spelcc/gate/commit/b8ad0577497205449e7b9c635e09f7062b4f9d73))
* route ngrok to the production gateway ([#30](https://github.com/spelcc/gate/issues/30)) ([acd8653](https://github.com/spelcc/gate/commit/acd8653ca87dd87cea67357526bc1877fefba65d))
* stabilize realtime terminal rendering ([#59](https://github.com/spelcc/gate/issues/59)) ([5c55c7c](https://github.com/spelcc/gate/commit/5c55c7c45d04e4c5cf62901a7f99e4d816eac7a7))
* test draft releases from commit SHA ([#51](https://github.com/spelcc/gate/issues/51)) ([b3491d6](https://github.com/spelcc/gate/commit/b3491d66b61bde51dad81fc3405447fa2c6666fa))
* **test:** update venv bootstrap assertion for find_compatible_python ([dfad906](https://github.com/spelcc/gate/commit/dfad906f45fa5f3c4810cc4881991ae5ea9de023))
* **test:** use active Python in onboarding sandbox ([516bc0e](https://github.com/spelcc/gate/commit/516bc0ed0097a6ed567d50e0b5d8f1ab1b125697))
* use venv interpreter for startup checks ([97ad220](https://github.com/spelcc/gate/commit/97ad2205aa68f876879e92614226c452eeee021a))


### Documentation

* Add DeepSeek Agent preprompt and refine .gitignore ([6510132](https://github.com/spelcc/gate/commit/6510132c388ba95fc519abee27fbeeae402a6a66))
* add VISION banner ([8ba925e](https://github.com/spelcc/gate/commit/8ba925eacb560889ce6bc62b47da795e2c33e23f))
* Update README: add features, remove userscript, update license ([608efeb](https://github.com/spelcc/gate/commit/608efebd6944e348e73b373697a7c147625c9d0f))


### Tests

* isolate Gate runtime environment ([#61](https://github.com/spelcc/gate/issues/61)) ([60226e4](https://github.com/spelcc/gate/commit/60226e4481a622dc60bb0e094405eca0e636b169))
* remove queue and skill catalog flakes ([61bd35b](https://github.com/spelcc/gate/commit/61bd35b55da4845e619f8a15dd08ed208513cf4c))


### Continuous Integration

* add Release Please automation ([#42](https://github.com/spelcc/gate/issues/42)) ([ed34f17](https://github.com/spelcc/gate/commit/ed34f17c9e120747b8d0d7a4081e29a1371352a6))
* allow manual release workflow runs ([#55](https://github.com/spelcc/gate/issues/55)) ([7b073c2](https://github.com/spelcc/gate/commit/7b073c2aab466ffb37bc352204249a79d3c5fb3d))


### Maintenance

* enforce pull request structure ([#33](https://github.com/spelcc/gate/issues/33)) ([3555090](https://github.com/spelcc/gate/commit/355509073789eb989b77dc3f2c263f4a21f2d15a))
* **main:** release 0.1.20 ([#48](https://github.com/spelcc/gate/issues/48)) ([966184c](https://github.com/spelcc/gate/commit/966184c38b6eb8b5214b206429c40459bb3d27f0))
* **main:** release 0.1.21 ([#49](https://github.com/spelcc/gate/issues/49)) ([4b67ca3](https://github.com/spelcc/gate/commit/4b67ca333ba95248611c91ba8d346f7b79d54f97))
* **main:** release 0.1.22 ([#56](https://github.com/spelcc/gate/issues/56)) ([5d6555c](https://github.com/spelcc/gate/commit/5d6555c656de9e5ba3f5eb9f4e94e4a027256e30))
* **main:** release 0.1.23 ([#57](https://github.com/spelcc/gate/issues/57)) ([3710985](https://github.com/spelcc/gate/commit/37109858f1966f62c3885a7713db07f8118e3e95))
* **main:** release 0.1.24 ([#60](https://github.com/spelcc/gate/issues/60)) ([0b35281](https://github.com/spelcc/gate/commit/0b352810f2f1106a1ebceefc2ce08b8bc3576478))
* **main:** release 0.1.25 ([#64](https://github.com/spelcc/gate/issues/64)) ([4f6d12a](https://github.com/spelcc/gate/commit/4f6d12a26dff9188af67e91d9e908746d6cce35c))
* **main:** release 0.1.26 ([#65](https://github.com/spelcc/gate/issues/65)) ([f65eb2c](https://github.com/spelcc/gate/commit/f65eb2c00115e3e89012fba091f4e321d1d190ce))
* **main:** release 0.1.27 ([#67](https://github.com/spelcc/gate/issues/67)) ([a865397](https://github.com/spelcc/gate/commit/a865397e1214c9d61c17b76ecccd8f6fdec3d711))
* **main:** release Gate 0.1.20 ([#44](https://github.com/spelcc/gate/issues/44)) ([c753f60](https://github.com/spelcc/gate/commit/c753f60b9d75eb05c88aa17cdaa2c163e5da8af1))
* **main:** release gate 0.2.0 ([#43](https://github.com/spelcc/gate/issues/43)) ([36db61b](https://github.com/spelcc/gate/commit/36db61bfe392db686a94908268ad8f40b0f7abdf))
* release 0.1.19-alpha ([41ab5d1](https://github.com/spelcc/gate/commit/41ab5d10847c7f15e319d5f7f50507949bac6f69))
* **release:** prepare v0.1.13 ([152aaca](https://github.com/spelcc/gate/commit/152aacadf1c86294da0fa3af8abcae49f5136508))
* **release:** prepare v0.1.14 ([0e60b29](https://github.com/spelcc/gate/commit/0e60b2998c6dcafee128bbc37bbba0323b1a4d32))
* **release:** prepare v0.1.18 ([56114c9](https://github.com/spelcc/gate/commit/56114c9b1c8d2a0b2fccdf225c1dc557de0443f2))
* **release:** prepare v0.1.19 ([148f679](https://github.com/spelcc/gate/commit/148f679ce34e5241bc5486889b37892f8b8859db))

## [0.1.27](https://github.com/spelcc/gate/compare/v0.1.26...v0.1.27) (2026-08-16)


### Fixed

* parse Release Please changelog headings ([#68](https://github.com/spelcc/gate/issues/68)) ([55cec7a](https://github.com/spelcc/gate/commit/55cec7a0b72df8dc5212c650d2e513ad90b8d458))

## [0.1.26](https://github.com/spelcc/gate/compare/v0.1.25...v0.1.26) (2026-08-16)


### Added

* add discover-first MCP tool exposure ([#66](https://github.com/spelcc/gate/issues/66)) ([06ba0e3](https://github.com/spelcc/gate/commit/06ba0e3374ebc988b88a59d2398e164b93d8f53b))

## [0.1.25](https://github.com/spelcc/gate/compare/v0.1.24...v0.1.25) (2026-08-15)


### Fixed

* keep MCP tool catalog stable by default ([#63](https://github.com/spelcc/gate/issues/63)) ([bfb477d](https://github.com/spelcc/gate/commit/bfb477da1d114b278dc91f74c8acaa38829ad820))

## [0.1.24](https://github.com/spelcc/gate/compare/v0.1.23...v0.1.24) (2026-08-14)


### Fixed

* stabilize realtime terminal rendering ([#59](https://github.com/spelcc/gate/issues/59)) ([5c55c7c](https://github.com/spelcc/gate/commit/5c55c7c45d04e4c5cf62901a7f99e4d816eac7a7))


### Tests

* isolate Gate runtime environment ([#61](https://github.com/spelcc/gate/issues/61)) ([60226e4](https://github.com/spelcc/gate/commit/60226e4481a622dc60bb0e094405eca0e636b169))

## [0.1.23](https://github.com/spelcc/gate/compare/v0.1.22...v0.1.23) (2026-08-06)


### Added

* add configurable MCP proxy aggregation ([d2c0d3d](https://github.com/spelcc/gate/commit/d2c0d3dddb44ffbb9af8691f9df348010c5cc580))
* add configurable MCP proxy aggregation ([38d77c9](https://github.com/spelcc/gate/commit/38d77c9e7931f1c43963f53e922b09ebdeb0b0e3))
* add configurable preprompt and hard limits for deepseek agent ([71b0e96](https://github.com/spelcc/gate/commit/71b0e969bea2f6ec6ecd0ad16bb0374fa0fedc34))
* add daemon log monitor ([#36](https://github.com/spelcc/gate/issues/36)) ([89c8f51](https://github.com/spelcc/gate/commit/89c8f5183a0cdb9ff57ed8e1b4bf5ccf54033608))
* add MCP auto-discovery and hot reload ([#27](https://github.com/spelcc/gate/issues/27)) ([2bbe9b3](https://github.com/spelcc/gate/commit/2bbe9b38ca349aefa0af58849ee46dd075c77617))
* add optional ChatGPT startup browser assist ([282e1ba](https://github.com/spelcc/gate/commit/282e1ba8fe52e233ad43c79080500f493bda3a85))
* add realtime call monitor ([#29](https://github.com/spelcc/gate/issues/29)) ([1c7d4c7](https://github.com/spelcc/gate/commit/1c7d4c7180d70501e0e4ae65db06ba0cda5fede0))
* add settings.yaml support and tool config ([549b5e8](https://github.com/spelcc/gate/commit/549b5e861ce7085ec2e9cd86425d5e74b2269ee3))
* expand realtime call details ([#53](https://github.com/spelcc/gate/issues/53)) ([ff691c7](https://github.com/spelcc/gate/commit/ff691c7f3ca0c70c44b79b90a2b5763912b5acb2))
* **safety:** add pluggable command guards ([fcdce47](https://github.com/spelcc/gate/commit/fcdce478068cb1a7a25767891fa71662c952717a))
* support prerelease and explicit version updates ([#35](https://github.com/spelcc/gate/issues/35)) ([c8647c2](https://github.com/spelcc/gate/commit/c8647c2dc4115e05436e24802ab962cb17a4b8e4))


### Fixed

* align alpha changelog with release workflow ([5810b6d](https://github.com/spelcc/gate/commit/5810b6d1627bad9097e3393c4cd73aecd404dd15))
* align v0.1.19 changelog with release workflow ([2478f47](https://github.com/spelcc/gate/commit/2478f47881e69ac85ea4c4179280c1aa5002afa8))
* avoid duplicate realtime log reader ([#54](https://github.com/spelcc/gate/issues/54)) ([92922bf](https://github.com/spelcc/gate/commit/92922bf8eb1e73339c53114092ef27fccc4c4d5b))
* **ci:** install pytest for test workflow ([17c2bf3](https://github.com/spelcc/gate/commit/17c2bf324aa47165bd4305ed9fea5354685f4149))
* configure filesystem roots from environment ([#3](https://github.com/spelcc/gate/issues/3)) ([f36acd4](https://github.com/spelcc/gate/commit/f36acd40b2fb54765a09f6d6368737aeac72a09f))
* convert async def tools to def to unblock the event loop ([#6](https://github.com/spelcc/gate/issues/6)) ([d5252fb](https://github.com/spelcc/gate/commit/d5252fb19256b880efa91648cae9fe3c320987f2))
* handle Python version, SSL, and ngrok web_allow_hosts edge cases ([7a723cc](https://github.com/spelcc/gate/commit/7a723cc2db6db43d5e437fce838d2fb076439045))
* handle Python version, SSL, and ngrok web_allow_hosts edge cases ([813204f](https://github.com/spelcc/gate/commit/813204fedfa2bbb89e44be686bded46aa2294010))
* **installer:** support Alpine Linux ([b8e053d](https://github.com/spelcc/gate/commit/b8e053dc5680a15b78142d86efc2c94aa0ad66f5))
* **installer:** support Alpine Linux ([521a6ff](https://github.com/spelcc/gate/commit/521a6ff5ab65b18dcd34efb1feeb4136c4f9e49a))
* probe gateway health on the resolved target ([#31](https://github.com/spelcc/gate/issues/31)) ([8677c4d](https://github.com/spelcc/gate/commit/8677c4ddd61a89a084491a502817a9a5240f4ff1))
* publish RFC 8414 OAuth metadata for issuer paths ([#52](https://github.com/spelcc/gate/issues/52)) ([91136ae](https://github.com/spelcc/gate/commit/91136aef7ddd04ddd297e940f77019794949d35f))
* reset Release Please state to v0.1.19 ([#47](https://github.com/spelcc/gate/issues/47)) ([b8ad057](https://github.com/spelcc/gate/commit/b8ad0577497205449e7b9c635e09f7062b4f9d73))
* route ngrok to the production gateway ([#30](https://github.com/spelcc/gate/issues/30)) ([acd8653](https://github.com/spelcc/gate/commit/acd8653ca87dd87cea67357526bc1877fefba65d))
* test draft releases from commit SHA ([#51](https://github.com/spelcc/gate/issues/51)) ([b3491d6](https://github.com/spelcc/gate/commit/b3491d66b61bde51dad81fc3405447fa2c6666fa))
* **test:** update venv bootstrap assertion for find_compatible_python ([dfad906](https://github.com/spelcc/gate/commit/dfad906f45fa5f3c4810cc4881991ae5ea9de023))
* **test:** use active Python in onboarding sandbox ([516bc0e](https://github.com/spelcc/gate/commit/516bc0ed0097a6ed567d50e0b5d8f1ab1b125697))
* use venv interpreter for startup checks ([97ad220](https://github.com/spelcc/gate/commit/97ad2205aa68f876879e92614226c452eeee021a))


### Documentation

* Add DeepSeek Agent preprompt and refine .gitignore ([6510132](https://github.com/spelcc/gate/commit/6510132c388ba95fc519abee27fbeeae402a6a66))
* add VISION banner ([8ba925e](https://github.com/spelcc/gate/commit/8ba925eacb560889ce6bc62b47da795e2c33e23f))
* Update README: add features, remove userscript, update license ([608efeb](https://github.com/spelcc/gate/commit/608efebd6944e348e73b373697a7c147625c9d0f))


### Tests

* remove queue and skill catalog flakes ([61bd35b](https://github.com/spelcc/gate/commit/61bd35b55da4845e619f8a15dd08ed208513cf4c))


### Continuous Integration

* add Release Please automation ([#42](https://github.com/spelcc/gate/issues/42)) ([ed34f17](https://github.com/spelcc/gate/commit/ed34f17c9e120747b8d0d7a4081e29a1371352a6))
* allow manual release workflow runs ([#55](https://github.com/spelcc/gate/issues/55)) ([7b073c2](https://github.com/spelcc/gate/commit/7b073c2aab466ffb37bc352204249a79d3c5fb3d))


### Maintenance

* enforce pull request structure ([#33](https://github.com/spelcc/gate/issues/33)) ([3555090](https://github.com/spelcc/gate/commit/355509073789eb989b77dc3f2c263f4a21f2d15a))
* **main:** release 0.1.20 ([#48](https://github.com/spelcc/gate/issues/48)) ([966184c](https://github.com/spelcc/gate/commit/966184c38b6eb8b5214b206429c40459bb3d27f0))
* **main:** release 0.1.21 ([#49](https://github.com/spelcc/gate/issues/49)) ([4b67ca3](https://github.com/spelcc/gate/commit/4b67ca333ba95248611c91ba8d346f7b79d54f97))
* **main:** release 0.1.22 ([#56](https://github.com/spelcc/gate/issues/56)) ([5d6555c](https://github.com/spelcc/gate/commit/5d6555c656de9e5ba3f5eb9f4e94e4a027256e30))
* **main:** release Gate 0.1.20 ([#44](https://github.com/spelcc/gate/issues/44)) ([c753f60](https://github.com/spelcc/gate/commit/c753f60b9d75eb05c88aa17cdaa2c163e5da8af1))
* **main:** release gate 0.2.0 ([#43](https://github.com/spelcc/gate/issues/43)) ([36db61b](https://github.com/spelcc/gate/commit/36db61bfe392db686a94908268ad8f40b0f7abdf))
* release 0.1.19-alpha ([41ab5d1](https://github.com/spelcc/gate/commit/41ab5d10847c7f15e319d5f7f50507949bac6f69))
* **release:** prepare v0.1.13 ([152aaca](https://github.com/spelcc/gate/commit/152aacadf1c86294da0fa3af8abcae49f5136508))
* **release:** prepare v0.1.14 ([0e60b29](https://github.com/spelcc/gate/commit/0e60b2998c6dcafee128bbc37bbba0323b1a4d32))
* **release:** prepare v0.1.18 ([56114c9](https://github.com/spelcc/gate/commit/56114c9b1c8d2a0b2fccdf225c1dc557de0443f2))
* **release:** prepare v0.1.19 ([148f679](https://github.com/spelcc/gate/commit/148f679ce34e5241bc5486889b37892f8b8859db))

## [0.1.22](https://github.com/spelcc/gate/compare/v0.1.21...v0.1.22) (2026-08-06)


### Added

* add configurable MCP proxy aggregation ([d2c0d3d](https://github.com/spelcc/gate/commit/d2c0d3dddb44ffbb9af8691f9df348010c5cc580))
* add configurable MCP proxy aggregation ([38d77c9](https://github.com/spelcc/gate/commit/38d77c9e7931f1c43963f53e922b09ebdeb0b0e3))
* add configurable preprompt and hard limits for deepseek agent ([71b0e96](https://github.com/spelcc/gate/commit/71b0e969bea2f6ec6ecd0ad16bb0374fa0fedc34))
* add daemon log monitor ([#36](https://github.com/spelcc/gate/issues/36)) ([89c8f51](https://github.com/spelcc/gate/commit/89c8f5183a0cdb9ff57ed8e1b4bf5ccf54033608))
* add MCP auto-discovery and hot reload ([#27](https://github.com/spelcc/gate/issues/27)) ([2bbe9b3](https://github.com/spelcc/gate/commit/2bbe9b38ca349aefa0af58849ee46dd075c77617))
* add optional ChatGPT startup browser assist ([282e1ba](https://github.com/spelcc/gate/commit/282e1ba8fe52e233ad43c79080500f493bda3a85))
* add realtime call monitor ([#29](https://github.com/spelcc/gate/issues/29)) ([1c7d4c7](https://github.com/spelcc/gate/commit/1c7d4c7180d70501e0e4ae65db06ba0cda5fede0))
* add settings.yaml support and tool config ([549b5e8](https://github.com/spelcc/gate/commit/549b5e861ce7085ec2e9cd86425d5e74b2269ee3))
* expand realtime call details ([#53](https://github.com/spelcc/gate/issues/53)) ([ff691c7](https://github.com/spelcc/gate/commit/ff691c7f3ca0c70c44b79b90a2b5763912b5acb2))
* **safety:** add pluggable command guards ([fcdce47](https://github.com/spelcc/gate/commit/fcdce478068cb1a7a25767891fa71662c952717a))
* support prerelease and explicit version updates ([#35](https://github.com/spelcc/gate/issues/35)) ([c8647c2](https://github.com/spelcc/gate/commit/c8647c2dc4115e05436e24802ab962cb17a4b8e4))


### Fixed

* align alpha changelog with release workflow ([5810b6d](https://github.com/spelcc/gate/commit/5810b6d1627bad9097e3393c4cd73aecd404dd15))
* align v0.1.19 changelog with release workflow ([2478f47](https://github.com/spelcc/gate/commit/2478f47881e69ac85ea4c4179280c1aa5002afa8))
* avoid duplicate realtime log reader ([#54](https://github.com/spelcc/gate/issues/54)) ([92922bf](https://github.com/spelcc/gate/commit/92922bf8eb1e73339c53114092ef27fccc4c4d5b))
* **ci:** install pytest for test workflow ([17c2bf3](https://github.com/spelcc/gate/commit/17c2bf324aa47165bd4305ed9fea5354685f4149))
* configure filesystem roots from environment ([#3](https://github.com/spelcc/gate/issues/3)) ([f36acd4](https://github.com/spelcc/gate/commit/f36acd40b2fb54765a09f6d6368737aeac72a09f))
* convert async def tools to def to unblock the event loop ([#6](https://github.com/spelcc/gate/issues/6)) ([d5252fb](https://github.com/spelcc/gate/commit/d5252fb19256b880efa91648cae9fe3c320987f2))
* handle Python version, SSL, and ngrok web_allow_hosts edge cases ([7a723cc](https://github.com/spelcc/gate/commit/7a723cc2db6db43d5e437fce838d2fb076439045))
* handle Python version, SSL, and ngrok web_allow_hosts edge cases ([813204f](https://github.com/spelcc/gate/commit/813204fedfa2bbb89e44be686bded46aa2294010))
* **installer:** support Alpine Linux ([b8e053d](https://github.com/spelcc/gate/commit/b8e053dc5680a15b78142d86efc2c94aa0ad66f5))
* **installer:** support Alpine Linux ([521a6ff](https://github.com/spelcc/gate/commit/521a6ff5ab65b18dcd34efb1feeb4136c4f9e49a))
* probe gateway health on the resolved target ([#31](https://github.com/spelcc/gate/issues/31)) ([8677c4d](https://github.com/spelcc/gate/commit/8677c4ddd61a89a084491a502817a9a5240f4ff1))
* publish RFC 8414 OAuth metadata for issuer paths ([#52](https://github.com/spelcc/gate/issues/52)) ([91136ae](https://github.com/spelcc/gate/commit/91136aef7ddd04ddd297e940f77019794949d35f))
* reset Release Please state to v0.1.19 ([#47](https://github.com/spelcc/gate/issues/47)) ([b8ad057](https://github.com/spelcc/gate/commit/b8ad0577497205449e7b9c635e09f7062b4f9d73))
* route ngrok to the production gateway ([#30](https://github.com/spelcc/gate/issues/30)) ([acd8653](https://github.com/spelcc/gate/commit/acd8653ca87dd87cea67357526bc1877fefba65d))
* test draft releases from commit SHA ([#51](https://github.com/spelcc/gate/issues/51)) ([b3491d6](https://github.com/spelcc/gate/commit/b3491d66b61bde51dad81fc3405447fa2c6666fa))
* **test:** update venv bootstrap assertion for find_compatible_python ([dfad906](https://github.com/spelcc/gate/commit/dfad906f45fa5f3c4810cc4881991ae5ea9de023))
* **test:** use active Python in onboarding sandbox ([516bc0e](https://github.com/spelcc/gate/commit/516bc0ed0097a6ed567d50e0b5d8f1ab1b125697))
* use venv interpreter for startup checks ([97ad220](https://github.com/spelcc/gate/commit/97ad2205aa68f876879e92614226c452eeee021a))


### Documentation

* Add DeepSeek Agent preprompt and refine .gitignore ([6510132](https://github.com/spelcc/gate/commit/6510132c388ba95fc519abee27fbeeae402a6a66))
* add VISION banner ([8ba925e](https://github.com/spelcc/gate/commit/8ba925eacb560889ce6bc62b47da795e2c33e23f))
* Update README: add features, remove userscript, update license ([608efeb](https://github.com/spelcc/gate/commit/608efebd6944e348e73b373697a7c147625c9d0f))


### Tests

* remove queue and skill catalog flakes ([61bd35b](https://github.com/spelcc/gate/commit/61bd35b55da4845e619f8a15dd08ed208513cf4c))


### Continuous Integration

* add Release Please automation ([#42](https://github.com/spelcc/gate/issues/42)) ([ed34f17](https://github.com/spelcc/gate/commit/ed34f17c9e120747b8d0d7a4081e29a1371352a6))
* allow manual release workflow runs ([#55](https://github.com/spelcc/gate/issues/55)) ([7b073c2](https://github.com/spelcc/gate/commit/7b073c2aab466ffb37bc352204249a79d3c5fb3d))


### Maintenance

* enforce pull request structure ([#33](https://github.com/spelcc/gate/issues/33)) ([3555090](https://github.com/spelcc/gate/commit/355509073789eb989b77dc3f2c263f4a21f2d15a))
* **main:** release 0.1.20 ([#48](https://github.com/spelcc/gate/issues/48)) ([966184c](https://github.com/spelcc/gate/commit/966184c38b6eb8b5214b206429c40459bb3d27f0))
* **main:** release 0.1.21 ([#49](https://github.com/spelcc/gate/issues/49)) ([4b67ca3](https://github.com/spelcc/gate/commit/4b67ca333ba95248611c91ba8d346f7b79d54f97))
* **main:** release Gate 0.1.20 ([#44](https://github.com/spelcc/gate/issues/44)) ([c753f60](https://github.com/spelcc/gate/commit/c753f60b9d75eb05c88aa17cdaa2c163e5da8af1))
* **main:** release gate 0.2.0 ([#43](https://github.com/spelcc/gate/issues/43)) ([36db61b](https://github.com/spelcc/gate/commit/36db61bfe392db686a94908268ad8f40b0f7abdf))
* release 0.1.19-alpha ([41ab5d1](https://github.com/spelcc/gate/commit/41ab5d10847c7f15e319d5f7f50507949bac6f69))
* **release:** prepare v0.1.13 ([152aaca](https://github.com/spelcc/gate/commit/152aacadf1c86294da0fa3af8abcae49f5136508))
* **release:** prepare v0.1.14 ([0e60b29](https://github.com/spelcc/gate/commit/0e60b2998c6dcafee128bbc37bbba0323b1a4d32))
* **release:** prepare v0.1.18 ([56114c9](https://github.com/spelcc/gate/commit/56114c9b1c8d2a0b2fccdf225c1dc557de0443f2))
* **release:** prepare v0.1.19 ([148f679](https://github.com/spelcc/gate/commit/148f679ce34e5241bc5486889b37892f8b8859db))

## [0.1.21](https://github.com/spelcc/gate/compare/v0.1.20...v0.1.21) (2026-08-01)


### Added

* add configurable MCP proxy aggregation ([d2c0d3d](https://github.com/spelcc/gate/commit/d2c0d3dddb44ffbb9af8691f9df348010c5cc580))
* add configurable MCP proxy aggregation ([38d77c9](https://github.com/spelcc/gate/commit/38d77c9e7931f1c43963f53e922b09ebdeb0b0e3))
* add configurable preprompt and hard limits for deepseek agent ([71b0e96](https://github.com/spelcc/gate/commit/71b0e969bea2f6ec6ecd0ad16bb0374fa0fedc34))
* add daemon log monitor ([#36](https://github.com/spelcc/gate/issues/36)) ([89c8f51](https://github.com/spelcc/gate/commit/89c8f5183a0cdb9ff57ed8e1b4bf5ccf54033608))
* add MCP auto-discovery and hot reload ([#27](https://github.com/spelcc/gate/issues/27)) ([2bbe9b3](https://github.com/spelcc/gate/commit/2bbe9b38ca349aefa0af58849ee46dd075c77617))
* add optional ChatGPT startup browser assist ([282e1ba](https://github.com/spelcc/gate/commit/282e1ba8fe52e233ad43c79080500f493bda3a85))
* add realtime call monitor ([#29](https://github.com/spelcc/gate/issues/29)) ([1c7d4c7](https://github.com/spelcc/gate/commit/1c7d4c7180d70501e0e4ae65db06ba0cda5fede0))
* add settings.yaml support and tool config ([549b5e8](https://github.com/spelcc/gate/commit/549b5e861ce7085ec2e9cd86425d5e74b2269ee3))
* **safety:** add pluggable command guards ([fcdce47](https://github.com/spelcc/gate/commit/fcdce478068cb1a7a25767891fa71662c952717a))
* support prerelease and explicit version updates ([#35](https://github.com/spelcc/gate/issues/35)) ([c8647c2](https://github.com/spelcc/gate/commit/c8647c2dc4115e05436e24802ab962cb17a4b8e4))


### Fixed

* align alpha changelog with release workflow ([5810b6d](https://github.com/spelcc/gate/commit/5810b6d1627bad9097e3393c4cd73aecd404dd15))
* align v0.1.19 changelog with release workflow ([2478f47](https://github.com/spelcc/gate/commit/2478f47881e69ac85ea4c4179280c1aa5002afa8))
* **ci:** install pytest for test workflow ([17c2bf3](https://github.com/spelcc/gate/commit/17c2bf324aa47165bd4305ed9fea5354685f4149))
* configure filesystem roots from environment ([#3](https://github.com/spelcc/gate/issues/3)) ([f36acd4](https://github.com/spelcc/gate/commit/f36acd40b2fb54765a09f6d6368737aeac72a09f))
* convert async def tools to def to unblock the event loop ([#6](https://github.com/spelcc/gate/issues/6)) ([d5252fb](https://github.com/spelcc/gate/commit/d5252fb19256b880efa91648cae9fe3c320987f2))
* handle Python version, SSL, and ngrok web_allow_hosts edge cases ([7a723cc](https://github.com/spelcc/gate/commit/7a723cc2db6db43d5e437fce838d2fb076439045))
* handle Python version, SSL, and ngrok web_allow_hosts edge cases ([813204f](https://github.com/spelcc/gate/commit/813204fedfa2bbb89e44be686bded46aa2294010))
* **installer:** support Alpine Linux ([b8e053d](https://github.com/spelcc/gate/commit/b8e053dc5680a15b78142d86efc2c94aa0ad66f5))
* **installer:** support Alpine Linux ([521a6ff](https://github.com/spelcc/gate/commit/521a6ff5ab65b18dcd34efb1feeb4136c4f9e49a))
* probe gateway health on the resolved target ([#31](https://github.com/spelcc/gate/issues/31)) ([8677c4d](https://github.com/spelcc/gate/commit/8677c4ddd61a89a084491a502817a9a5240f4ff1))
* reset Release Please state to v0.1.19 ([#47](https://github.com/spelcc/gate/issues/47)) ([b8ad057](https://github.com/spelcc/gate/commit/b8ad0577497205449e7b9c635e09f7062b4f9d73))
* route ngrok to the production gateway ([#30](https://github.com/spelcc/gate/issues/30)) ([acd8653](https://github.com/spelcc/gate/commit/acd8653ca87dd87cea67357526bc1877fefba65d))
* **test:** update venv bootstrap assertion for find_compatible_python ([dfad906](https://github.com/spelcc/gate/commit/dfad906f45fa5f3c4810cc4881991ae5ea9de023))
* **test:** use active Python in onboarding sandbox ([516bc0e](https://github.com/spelcc/gate/commit/516bc0ed0097a6ed567d50e0b5d8f1ab1b125697))
* use venv interpreter for startup checks ([97ad220](https://github.com/spelcc/gate/commit/97ad2205aa68f876879e92614226c452eeee021a))


### Documentation

* Add DeepSeek Agent preprompt and refine .gitignore ([6510132](https://github.com/spelcc/gate/commit/6510132c388ba95fc519abee27fbeeae402a6a66))
* add VISION banner ([8ba925e](https://github.com/spelcc/gate/commit/8ba925eacb560889ce6bc62b47da795e2c33e23f))
* Update README: add features, remove userscript, update license ([608efeb](https://github.com/spelcc/gate/commit/608efebd6944e348e73b373697a7c147625c9d0f))


### Tests

* remove queue and skill catalog flakes ([61bd35b](https://github.com/spelcc/gate/commit/61bd35b55da4845e619f8a15dd08ed208513cf4c))


### Continuous Integration

* add Release Please automation ([#42](https://github.com/spelcc/gate/issues/42)) ([ed34f17](https://github.com/spelcc/gate/commit/ed34f17c9e120747b8d0d7a4081e29a1371352a6))


### Maintenance

* enforce pull request structure ([#33](https://github.com/spelcc/gate/issues/33)) ([3555090](https://github.com/spelcc/gate/commit/355509073789eb989b77dc3f2c263f4a21f2d15a))
* **main:** release 0.1.20 ([#48](https://github.com/spelcc/gate/issues/48)) ([966184c](https://github.com/spelcc/gate/commit/966184c38b6eb8b5214b206429c40459bb3d27f0))
* **main:** release Gate 0.1.20 ([#44](https://github.com/spelcc/gate/issues/44)) ([c753f60](https://github.com/spelcc/gate/commit/c753f60b9d75eb05c88aa17cdaa2c163e5da8af1))
* **main:** release gate 0.2.0 ([#43](https://github.com/spelcc/gate/issues/43)) ([36db61b](https://github.com/spelcc/gate/commit/36db61bfe392db686a94908268ad8f40b0f7abdf))
* release 0.1.19-alpha ([41ab5d1](https://github.com/spelcc/gate/commit/41ab5d10847c7f15e319d5f7f50507949bac6f69))
* **release:** prepare v0.1.13 ([152aaca](https://github.com/spelcc/gate/commit/152aacadf1c86294da0fa3af8abcae49f5136508))
* **release:** prepare v0.1.14 ([0e60b29](https://github.com/spelcc/gate/commit/0e60b2998c6dcafee128bbc37bbba0323b1a4d32))
* **release:** prepare v0.1.18 ([56114c9](https://github.com/spelcc/gate/commit/56114c9b1c8d2a0b2fccdf225c1dc557de0443f2))
* **release:** prepare v0.1.19 ([148f679](https://github.com/spelcc/gate/commit/148f679ce34e5241bc5486889b37892f8b8859db))

## [0.1.20](https://github.com/spelcc/gate/compare/v0.1.19...v0.1.20) (2026-08-01)


### Fixed

* reset Release Please state to v0.1.19 ([#47](https://github.com/spelcc/gate/issues/47)) ([b8ad057](https://github.com/spelcc/gate/commit/b8ad0577497205449e7b9c635e09f7062b4f9d73))


### Continuous Integration

* add Release Please automation ([#42](https://github.com/spelcc/gate/issues/42)) ([ed34f17](https://github.com/spelcc/gate/commit/ed34f17c9e120747b8d0d7a4081e29a1371352a6))


### Maintenance

* **main:** release Gate 0.1.20 ([#44](https://github.com/spelcc/gate/issues/44)) ([c753f60](https://github.com/spelcc/gate/commit/c753f60b9d75eb05c88aa17cdaa2c163e5da8af1))
* **main:** release gate 0.2.0 ([#43](https://github.com/spelcc/gate/issues/43)) ([36db61b](https://github.com/spelcc/gate/commit/36db61bfe392db686a94908268ad8f40b0f7abdf))

## [0.1.20](https://github.com/spelcc/gate/compare/v0.1.19...v0.1.20) (2026-08-01)

### Fixed

- Sort completed realtime calls by date regardless of terminal status.
- Sort calls without timestamps after dated calls within the same status group.
- Preserve Gate's historical `vX.Y.Z` tag format in Release Please.

### Continuous Integration

- Add Release Please automation for version pull requests, tags, draft releases, tested archives, and checksums.
- Publish draft releases only after release tests and asset uploads pass.

## 0.1.19

### Added

- Add deterministic `skills_create` support for creating validated local skill packages.
- Add the builtin `skill-creator` workflow.

### Fixed

- Add a Windows-compatible atomic publication fallback when `dir_fd` APIs are unavailable.
- Harden POSIX skill publication against symlink swaps and temporary-directory races.
- Fix secure skill publication on macOS with Python 3.14 by resolving directory descriptors through `F_GETPATH` while preserving fd-pinned writes on Linux.
- Preserve the original publication error during temporary-directory cleanup and log unexpected cleanup failures.

### Tests

- Add focused coverage for macOS descriptor resolution, fail-closed behavior, cleanup, and platform-specific write paths.

## 0.1.18

### Added

- Add a daemon log monitor for viewing Gate runtime output without opening raw log files.
- Add Tailscale as a tunnel provider alongside ngrok.
- Add MCP server auto-discovery and hot reload through the local registry.
- Add explicit version and prerelease update support to the Gate CLI.

### Changed

- Enforce a structured pull request template and validate pull request bodies in CI.
- Improve release asset and updater validation for explicit and prerelease versions.

### Tests

- Add focused coverage for daemon logs, tunnel providers, MCP registry reloads, release assets, updater behavior, and pull request validation.

## 0.1.17

### Fixed

- Probe gateway readiness through the same resolved LAN target used by ngrok on macOS.
- Avoid false startup timeouts when another process owns loopback port `8761`.

### Tests

- Add coverage ensuring gateway health checks follow the resolved ngrok target and retain the loopback fallback elsewhere.

## 0.1.16

### Fixed

- Route ngrok to the active macOS LAN address so a loopback-only listener on port `8761` cannot expose the wrong OAuth/JWKS instance.
- Add `GATE_NGROK_TARGET` as an explicit cross-platform upstream override.

### Tests

- Add focused coverage for macOS address discovery, fallback behavior, overrides, and launcher integration.

## 0.1.15

### Added

- Add an interactive **Realtime calls** monitor with bounded, redacted command previews and lifecycle status.
- Add a README security overview for the built-in safeguard and one-click verified `dcg` installation.

### Changed

- Keep realtime monitoring active in both blocking and queued command modes.
- Rename the asynchronous queue opt-in to `--queue` and `MCP_COMMAND_QUEUE_ENABLED`, while preserving the legacy realtime aliases.
- Guide agents to poll queued commands through `get_command_state` instead of reading internal log references.

### Security

- Keep realtime snapshots private, bounded, and sanitized before persistence.
- Update pinned authentication, multipart, and cryptography dependencies.

### Tests

- Add focused coverage for realtime rendering, state ordering, redaction, blocking-mode monitoring, and queue polling.

## 0.1.14

### Fixed

- Detect a compatible Python interpreter before creating the virtual environment, with clearer handling for unsupported Python versions.
- Use the virtual environment interpreter for startup dependency and SSL checks.
- Handle missing SSL support and ngrok `web_allow_hosts` startup edge cases more reliably.
- Reduce flaky command queue, onboarding, skill catalog, and startup tests.

### Tests

- Add focused coverage for Python bootstrap, startup compatibility, onboarding, and command queue behavior.

## 0.1.13

### Fixed

- Support Alpine Linux 3.22 in the installer by installing Node.js 22 with `apk` instead of requesting unavailable musl binaries through NVM.
- Run NVM outside `nounset` mode with a defined temporary directory on non-Alpine systems.

### Tests

- Add automated Alpine installer coverage using the `alpine:3.22` container image.

## 0.1.12

### Added

- Add pluggable destructive-command guards with dependency-free `builtin` and optional verified `dcg` providers.
- Return structured denial reasons and safe remediation commands before destructive shell execution.
- Guard local and proxied shell tools, including `run_command` and `filesystem_execute_tool`.
- Add temporary `gate --noguard` support for a single launch without changing saved configuration.
- Add first-run command guard provider selection.

### Changed

- Encrypt queued command payloads so commands can safely resume after restart while displayed state remains redacted.
- Add tool, host, platform, working directory, provider, rule, and remediation details to guard audit events.

### Security

- Redact secrets from command logs, queue state, proxy logs, and conversation logs.
- Verify pinned DCG release checksums and executable versions before use, with automatic fallback to the built-in provider.

## 0.1.11

### Fixed

- Keep the running Gate instance online when update discovery or download fails, including GitHub API rate limits.
- Stop and restart services only after a release has been downloaded, verified, and installed successfully.

## 0.1.10

### Changed

- Replace fixed 2-second startup waits with health-check polls for faster startup.
- Gateway waits for `/oauth/health` instead of sleeping blindly.
- ngrok waits for the local API tunnel response instead of sleeping blindly.
- Move GitHub update check to a background thread so it never blocks the UI.

### Fixed

- Skip redundant dependency installation on warm starts using an mtime sentinel.

## 0.1.9

### Fixed

- Treat an existing live daemon PID file as an already-running Gate instance instead of failing interactive startup.
- Remove stale daemon PID files automatically before interactive startup.
- Isolate onboarding and CLI tests from the developer's real Gate config, logs, and release state.

## 0.1.8

### Added

- Add an aligned interactive controls menu for connection details, changelog, updates, and shutdown.
- Allow connection details and changelog panels to be toggled with their shortcut or closed with Escape.
- Relaunch Gate automatically after a successful interactive update.

### Changed

- Replace the single-line startup prompt with a clearer multi-line terminal interface.

## 0.1.7

### Fixed

- Make `gate stop` reliably terminate orphaned gateway processes on WSL by killing matching gateway processes and the listener on port 8761, with TERM-to-KILL escalation.

## 0.1.6

### Added

- Check for a newer stable Gate release at interactive startup.
- Show `press u to install` when an update is available.
- Stop managed services before launching the update command.

### Fixed

- Stop gateway processes still listening on port 8761 even when the PID file is missing or stale.
- Make the CLI version test read `VERSION` dynamically instead of requiring edits for every release.

## 0.1.5

### Changed

- Remove all automatic browser-opening behavior from installation and normal Gate usage.
- Require Python tests and duplicate-code checks to pass before creating a GitHub Release.
- Stabilize the interactive Ctrl+C test on Linux CI.

## 0.1.4

### Fixed

- Handle Ctrl+C in the global Gate CLI without displaying a Python `KeyboardInterrupt` traceback.
- Return the standard shell interrupt exit code `130` after a clean shutdown.

## 0.1.3

### Fixed

- Install runtime dependencies through `uv pip` when Gate uses an uv-managed virtual environment without bundled `pip`.
- Replace the active release symlink atomically on macOS without following the previous directory symlink.

## 0.1.2

### Fixed

- Expose the installed `src` directory through `PYTHONPATH` so the global `gate` launcher can import `gate_cli`.

### Changed

- Rewrite the README around Gate as a local MCP reverse proxy for ChatGPT web and iOS.
- Add the Agent Skills catalogue to the README and link to the detailed MCP and Skills documentation.
- Remove the README logo and contributor-focused test section.

## 0.1.1

### Changed

- Renamed the project and all legacy user-facing references to Gate.
- Moved the canonical GitHub repository to `arthurlacoste/gate`.
- Renamed runtime identifiers, environment variables, package metadata and widget URIs to Gate.

## 0.1.0

### Added

- One-line user installation through `install.sh`.
- Global `gate` command in `~/.local/bin`.
- User-managed Python 3.12 through uv and Node 22 through nvm.
- Automatic ngrok installation and first-run authentication.
- Stable tag and edge update channels.
- Atomic release activation with rollback state.
- Persistent config, data, logs and skills outside release directories.
- `gate doctor`, `gate logs`, `gate secret` and uninstall commands.
- Reuse of the onboarding ngrok tunnel during the first launch.
