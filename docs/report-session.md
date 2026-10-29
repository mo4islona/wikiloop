# The session-report bucket

`wiki-report-session` uploads a bad session's transcript, redacted, for a maintainer to
replay. The bucket must be write-only for everyone in the organization: create, no list, no
read back, no overwrite. Readers are named one by one, because a reader sees every transcript.
Objects expire after `report_session.ttl_days`.

## Google Cloud Storage

```
BUCKET=gs://<org>-agent-sessions
gcloud storage buckets create $BUCKET --project=<project> --location=<region> \
  --uniform-bucket-level-access --public-access-prevention
echo '{"rule":[{"action":{"type":"Delete"},"condition":{"age":30}}]}' > /tmp/lifecycle.json
gcloud storage buckets update $BUCKET --lifecycle-file=/tmp/lifecycle.json

# Project viewers inherit read access through legacy roles; remove it so the reader list is the whole truth.
for role in roles/storage.legacyBucketReader roles/storage.legacyObjectReader; do
  gcloud storage buckets remove-iam-policy-binding $BUCKET --member=projectViewer:<project> --role=$role
done

gcloud storage buckets add-iam-policy-binding $BUCKET --member=domain:<your domain> --role=roles/storage.objectCreator
gcloud storage buckets add-iam-policy-binding $BUCKET --member=user:<maintainer> --role=roles/storage.objectViewer
```

## Amazon S3

Create the bucket with Block Public Access on and a lifecycle rule that expires objects after
30 days. Give the organization's role `s3:PutObject` on `arn:aws:s3:::<bucket>/*` and nothing
else; give maintainers `s3:GetObject` and `s3:ListBucket`. Object Lock or a deny on
`s3:PutObject` with an existing key is not needed: each upload's prefix carries the minute.

## Then

```toml
[report_session]
kind = "gcs"                              # or "s3"
bucket = "gs://<org>-agent-sessions"
```

and `wikiloop build`. The SessionStart line that names the transcript appears only when a
bucket is set.
