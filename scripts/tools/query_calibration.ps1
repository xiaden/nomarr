$auth = [Convert]::ToBase64String([Text.Encoding]::ASCII.GetBytes("root:nomarr_dev_password"))
$h = @{Authorization="Basic $auth"}

# Which head names exist in segment_scores_stats?
$q1 = '{"query":"FOR s IN segment_scores_stats COLLECT head=s.head_name WITH COUNT INTO n RETURN {head,n}"}'
$r1 = Invoke-RestMethod -Uri "http://127.0.0.1:8529/_db/nomarr/_api/cursor" -Method Post -ContentType "application/json" -Headers $h -Body $q1
Write-Host "=== Head names in segment_scores_stats ==="
$r1.result | Sort-Object head | ForEach-Object { Write-Host "  $($_.head): $($_.n) entries" }

# How many total docs?
$q2 = '{"query":"RETURN LENGTH(segment_scores_stats)"}'
$r2 = Invoke-RestMethod -Uri "http://127.0.0.1:8529/_db/nomarr/_api/cursor" -Method Post -ContentType "application/json" -Headers $h -Body $q2
Write-Host "Total segment_scores_stats docs: $($r2.result[0])"

# Sample an engagement numeric tag to confirm the raw scores are stored
$q3 = '{"query":"FOR t IN tags FILTER CONTAINS(t.name, \"engagement\") LIMIT 3 RETURN {name:t.name, val:t.value}"}'
$r3 = Invoke-RestMethod -Uri "http://127.0.0.1:8529/_db/nomarr/_api/cursor" -Method Post -ContentType "application/json" -Headers $h -Body $q3
Write-Host "=== Sample engagement tags in DB ==="
$r3.result | ForEach-Object { Write-Host "  $($_.rel) = $($_.val)" }
