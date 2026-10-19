# -----------------------------------------------------------------------------
# Argo CD - the hand-over point. Terraform installs Argo CD and ONE root
# Application; from then on Argo CD keeps the cluster matching gitops/ in Git.
# -----------------------------------------------------------------------------
resource "helm_release" "argocd" {
  name             = "argocd"
  namespace        = "argocd"
  create_namespace = true
  repository       = "https://argoproj.github.io/argo-helm"
  chart            = "argo-cd"
  version          = var.argocd_chart_version
  wait             = true
  timeout          = 600

  values = [yamlencode({
    global = {
      nodeSelector = local.system_node_selector
    }

    # Reached only through kubectl port-forward: no load balancer, nothing
    # public, and nothing extra to clean up on teardown
    configs = {
      params = {
        "server.insecure" = true
      }
    }

    # Not needed for a single-user platform
    dex           = { enabled = false }
    notifications = { enabled = false }
  })]

  depends_on = [helm_release.karpenter]
}

# Root "app of apps": points Argo CD at gitops/bootstrap/, where each file is an
# Application for one platform component. Created via the argocd-apps chart
# because Terraform can't plan a CRD-based resource before the CRD exists.
#
# No resources-finalizer on purpose: during teardown Argo CD's controller is
# scaled to zero, and a finalizer would then block the Application's deletion.
resource "helm_release" "argocd_apps" {
  name       = "argocd-apps"
  namespace  = "argocd"
  repository = "https://argoproj.github.io/argo-helm"
  chart      = "argocd-apps"
  version    = var.argocd_apps_chart_version

  values = [yamlencode({
    applications = {
      root = {
        namespace = "argocd"
        project   = "default"
        source = {
          repoURL        = var.gitops_repo_url
          targetRevision = "main"
          path           = "gitops/bootstrap"
        }
        destination = {
          server    = "https://kubernetes.default.svc"
          namespace = "argocd"
        }
        syncPolicy = {
          automated = {
            prune    = true
            selfHeal = true
          }
        }
      }
    }
  })]

  depends_on = [helm_release.argocd]
}
