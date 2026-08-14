# Official checksum verification

An HTTP 200 response proves that bytes arrived. It does not prove that those
bytes are the exact archive the data publisher intended. MarketPulse therefore
checks source identity and content integrity before parsing.

## Trust boundary

Binance publishes one `.CHECKSUM` file beside every public ZIP. Its official
public-data documentation recommends SHA-256 verification and notes that an
archive can be replaced later when source issues are discovered.

For the fixed learning source, MarketPulse retrieves:

- `BTCUSDT-1m-2024-01-01.zip.CHECKSUM`
- `BTCUSDT-1m-2024-01-01.zip`

Both resources use the Day 8 timeout, retry, response-size, and partial-file
controls. Retrieval alone does not publish the ZIP.

## Accepted checksum contract

The checksum file is untrusted input. MarketPulse accepts only:

1. at most 1 KiB of ASCII text;
2. exactly one record;
3. exactly 64 hexadecimal SHA-256 characters;
4. two spaces separating the digest and file name, matching Binance's current
   published format; and
5. the exact source archive name, not another symbol, interval, date, or path.

The digest is normalized to lowercase. Extra records, a different filename,
non-ASCII bytes, incomplete hashes, and oversized files fail explicitly.

## Candidate-to-published flow

```text
official CHECKSUM --bounded download--> private checksum candidate
official ZIP      --bounded download--> private archive candidate
                                      |
                                      v
                         parse exact checksum record
                                      |
                                      v
                         calculate candidate ZIP SHA-256
                                      |
                    match ------------+------------ mismatch
                      |                               |
                      v                               v
          publish ZIP + CHECKSUM pair       delete candidates and fail
                      |
                      v
              parse trusted candle rows
```

A failed refresh never publishes either candidate and leaves an older pair
untouched. Because publishing two separate files cannot be one filesystem
operation, every cached run verifies the archive against its saved official
record again before parsing. The Day 10 manifest will add durable run state and
recovery evidence around this boundary.

## Error categories

- `ChecksumFormatError`: the publisher record is empty, oversized, non-ASCII,
  malformed, contains more than one line, or names the wrong file.
- `ChecksumReadError`: a checksum or archive cannot be read.
- `ChecksumMismatchError`: the calculated archive digest differs from the
  published digest and reports both values.
- `SampleDownloadError`: downloading, checking, or publishing a fresh pair
  failed.
- `SampleIntegrityError`: a cached pair cannot be verified before parsing.

These categories let later manifests record `download_failed`,
`checksum_invalid`, and `checksum_mismatch` without interpreting arbitrary
library messages.

## Evidence

Run the checksum and sample tests without network access:

```powershell
uv run pytest tests/test_checksum.py tests/test_binance_sample.py -q
```

Then verify the real public pair:

```powershell
uv run marketpulse fetch-sample --limit 5 --force
```

The command must report `Official checksum: verified`. The currently published
2024-01-01 BTCUSDT archive has SHA-256
`4ec2915e610ab4e9a4d5e86a5ada1c15bbf6b5db343cdb385681d6ac97166a4e`.

## References

- [Binance public-data repository: CHECKSUM](https://github.com/binance/binance-public-data#checksum)
- [Python 3.12 hashlib documentation](https://docs.python.org/3.12/library/hashlib.html)
- [Python 3.12 hmac.compare_digest documentation](https://docs.python.org/3.12/library/hmac.html#hmac.compare_digest)
