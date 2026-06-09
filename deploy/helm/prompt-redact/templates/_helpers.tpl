{{/* Chart name, overridable. */}}
{{- define "prompt-redact.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{/* Common metadata labels (not used as selectors). */}}
{{- define "prompt-redact.labels" -}}
app.kubernetes.io/name: {{ include "prompt-redact.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/part-of: prompt-redact
app.kubernetes.io/managed-by: {{ .Release.Service }}
helm.sh/chart: {{ printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" }}
{{- end -}}

{{/* Fully-qualified image refs, with the optional registry prefix. */}}
{{- define "prompt-redact.sidecarImage" -}}
{{- if .Values.image.registry -}}{{ .Values.image.registry }}/{{ end -}}
{{- .Values.sidecar.image.repository }}:{{ .Values.sidecar.image.tag }}
{{- end -}}

{{- define "prompt-redact.frontendImage" -}}
{{- if .Values.image.registry -}}{{ .Values.image.registry }}/{{ end -}}
{{- .Values.frontend.image.repository }}:{{ .Values.frontend.image.tag }}
{{- end -}}

{{/* Render image pull secrets if any. */}}
{{- define "prompt-redact.imagePullSecrets" -}}
{{- with .Values.image.pullSecrets }}
imagePullSecrets:
{{- toYaml . | nindent 0 }}
{{- end }}
{{- end -}}
