# imc-reply-gate-core

The code of Rob's imc-reply-gate: Claude hooks that check replies before they are sent.

This repository is fetched at run time by the imc-reply-gate loader plug-in (private marketplace robkh1984/imc-claude-plugins). The loader reads MANIFEST.json, downloads any file whose sha256 changed, refuses the update if any hash or path is wrong or the serial goes backwards, and falls back to its last good copy or to the copy bundled in the plug-in.

To release: change the files, bump `serial` (and `version`) in MANIFEST.json with every file's sha256, commit to main. Sessions pick it up within the loader's 10-minute refresh, plus GitHub's raw-file caching.

The hash list catches a damaged download. It does not protect against someone who controls this repository.
