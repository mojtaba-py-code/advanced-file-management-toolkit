# Security Policy

## Supported versions

| Version | Supported |
| ------- | --------- |
| 1.0.x   | ✅        |

## Reporting a vulnerability

Please **do not open a public issue** for a security problem.

Report it privately through GitHub's
[private vulnerability reporting](https://github.com/mojtaba-py-code/advanced-file-management-toolkit/security/advisories/new)
form. Include the version, your platform, reproduction steps, and the impact you
believe it has.

You can expect an acknowledgement within 72 hours and a fix or a clear decision
within 30 days for confirmed issues.

## Threat model

This toolkit moves, renames and deletes files on the machine that runs it. It
runs with the privileges of the invoking user and is designed around the
assumption that **the paths and archives it is pointed at may be hostile**, while
the person running it is trusted.

### What the toolkit defends against

| Threat | Defence |
| --- | --- |
| Directory traversal | Every path is resolved (collapsing `..`) before use; `safe_join` re-checks that composed paths stay under their base |
| Zip-slip / tar-slip | Each archive member's destination is validated before extraction; traversing members are refused |
| Malicious archive members | Non-regular tar members (symlinks, devices, FIFOs) are skipped rather than written |
| Symlink escape | Symlinks are refused by default and never followed during directory walks |
| Symlink loops | Directory walks run with `followlinks=False`, so a cycle cannot trap the walk |
| Damage to the OS | A deny-list refuses writes to curated system directories and to a filesystem root itself; every destructive entry point enforces it |
| Accidental data loss | Destructive actions require `--force` or an interactive confirmation, and all of them support `--dry-run` |
| Silent overwrites | Colliding writes are auto-renamed rather than clobbering an existing file |
| Silent corruption | Backups are re-hashed after writing and verified against a manifest |

### What it explicitly does not defend against

- **A malicious operator.** The toolkit constrains mistakes, not a user who
  deliberately points it somewhere destructive with `--force`.
- **Privilege escalation.** It never elevates; it runs as the invoking user.
- **Decompression bombs.** Extraction does not currently cap the expanded size of
  an archive, so a crafted archive can fill the target disk. Extract untrusted
  archives onto a volume you can afford to fill.
- **TOCTOU races.** A path validated and then modified by another process
  between the check and the operation is not detected.
- **Cryptographic guarantees.** Checksums detect accidental corruption. They are
  not a defence against an attacker who can rewrite both a file and its manifest.

## Confining operations

Set `security.allowed_roots` in `config/settings.yaml` to restrict every path the
toolkit validates to an explicit allow-list of directories. It is applied once at
startup, before any command runs, and enforced inside `validate_path` so a call
site cannot forget it. This is the strongest single control the toolkit offers
and is recommended for unattended or scheduled runs:

```yaml
security:
  allowed_roots:
    - /srv/data
    - /mnt/backup
```

An invalid entry is rejected at startup rather than skipped, so a typo in the
list can never silently widen what is permitted. Refusing protected OS locations
and requiring confirmation before a destructive action are always on and are
deliberately not configurable.
