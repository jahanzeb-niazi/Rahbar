param(
    [Parameter(Mandatory)][ValidateSet('ingest','eval','release','coverage')][string]$Action,
    [string]$Name,
    [ValidateSet('','a','b','deleted')][string]$Batch = '',
    [string]$Collection = '',
    [string]$Restore = '',
    [string]$Endpoint = 'http://api:8000',
    [string]$Reference = '',
    [string]$Golden = 'golden.jsonl'
)
$ErrorActionPreference = 'Stop'
$PSNativeCommandUseErrorActionPreference = $true
$namespace = 'rahbar'
$root = Split-Path -Parent $PSScriptRoot

function Apply-Job($job) {
    $job | ConvertTo-Json -Depth 100 | kubectl apply -f -
}

switch ($Action) {
    ingest {
        if (!$Name) { throw 'Specify a unique Job name with -Name.' }
        $job = kubectl -n $namespace create job $Name --from=cronjob/ragops-ingest --dry-run=client -o json |
            ConvertFrom-Json
        $container = $job.spec.template.spec.containers[0]
        if ($Batch) { $container.env += @{name='RAGOPS_BATCH'; value=$Batch} }
        if ($Collection) { $container.env += @{name='CHROMA_COLLECTION'; value=$Collection} }
        if ($Restore) { $container.env += @{name='RAGOPS_RESTORE'; value=$Restore} }
        Apply-Job $job
    }
    eval {
        if (!$Name) { throw 'Specify a unique Job name with -Name.' }
        $job = kubectl create --dry-run=client -f (Join-Path $root 'k8s/eval-job.yaml') -o json |
            ConvertFrom-Json
        $job.metadata.name = $Name
        if ($Endpoint -eq 'http://api-candidate:8000') {
            $revision = kubectl -n $namespace get deployment api-candidate -o 'jsonpath={.metadata.generation}'
            $job.metadata | Add-Member -MemberType NoteProperty -Name annotations -Value ([pscustomobject]@{'ragops/candidate-generation' = [string]$revision}) -Force
        }
        $job.spec.template.spec.containers[0].env = @(
            @{name='EVAL_API'; value=$Endpoint},
            @{name='EVAL_NAME'; value=$Name},
            @{name='EVAL_REFERENCE'; value=$Reference},
            @{name='EVAL_GOLDEN'; value=$Golden}
        )
        Apply-Job $job
    }
    coverage {
        if (!$Name) { throw 'Specify a unique Job name with -Name.' }
        $job = kubectl create --dry-run=client -f (Join-Path $root 'k8s/eval-job.yaml') -o json |
            ConvertFrom-Json
        $job.metadata.name = $Name
        $job.spec.template.spec.containers[0].args = @(
            'exec python /app/eval/assignment3.py coverage --ollama "$OLLAMA_URL" --model "$EMBED_MODEL" --golden "/app/eval/$EVAL_GOLDEN" --out /lake/results'
        )
        $job.spec.template.spec.containers[0].env = @(@{name='EVAL_GOLDEN'; value=$Golden})
        Apply-Job $job
    }
    release {
        if (!$Name) { throw 'Specify the passing candidate evaluation Job with -Name.' }
        $job = kubectl -n $namespace get job $Name -o json | ConvertFrom-Json
        $envValues = @{}
        foreach ($variable in $job.spec.template.spec.containers[0].env) {
            $envValues[$variable.name] = $variable.value
        }
        if ($envValues.EVAL_API -ne 'http://api-candidate:8000' -or !$envValues.EVAL_REFERENCE) {
            throw 'Release requires a gated evaluation against the candidate Service.'
        }
        if (!(($job.status.conditions | Where-Object { $_.type -eq 'Complete' -and $_.status -eq 'True' }))) {
            throw 'Candidate evaluation did not complete successfully.'
        }
        $result = kubectl -n $namespace logs "job/$Name"
        if ('GATE PASS' -notin $result) { throw 'Candidate evaluation has no passing release gate.' }
        $candidate = kubectl -n $namespace get deployment api-candidate -o json | ConvertFrom-Json
        if ($job.metadata.annotations['ragops/candidate-generation'] -ne [string]$candidate.metadata.generation) {
            throw 'The candidate Deployment changed after this evaluation was started.'
        }
        $candidateEnv = @{}
        foreach ($variable in $candidate.spec.template.spec.containers[0].env) {
            $candidateEnv[$variable.name] = $variable.value
        }
        kubectl -n $namespace set env deployment/api "CHROMA_COLLECTION=$($candidateEnv.CHROMA_COLLECTION)" "TOP_K=$($candidateEnv.TOP_K)"
        kubectl -n $namespace rollout status deployment/api --timeout=300s
    }
}
