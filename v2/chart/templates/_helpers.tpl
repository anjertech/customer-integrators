{{- define "presa-etl.image.orchestrator" -}}
{{ .Values.image.registry }}/{{ .Values.image.orchestrator.repository }}:{{ .Values.image.orchestrator.tag }}
{{- end -}}

{{- define "presa-etl.image.worker" -}}
{{ .Values.image.registry }}/{{ .Values.image.worker.repository }}:{{ .Values.image.worker.tag }}
{{- end -}}

{{- define "presa-etl.image.vpnSidecar" -}}
{{ .Values.image.registry }}/{{ .Values.image.vpnSidecar.repository }}:{{ .Values.image.vpnSidecar.tag }}
{{- end -}}
