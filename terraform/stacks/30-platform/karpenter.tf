# -----------------------------------------------------------------------------
# Karpenter - AWS side: controller role (via Pod Identity), node role + access
# entry, and an SQS queue fed by EventBridge so Karpenter hears about Spot
# interruptions ~2 minutes ahead and drains nodes gracefully.
# -----------------------------------------------------------------------------
module "karpenter" {
  # Same pinned commit as the EKS module in 20-eks (release v21.26.0)
  source = "git::https://github.com/terraform-aws-modules/terraform-aws-eks.git//modules/karpenter?ref=323c633629b8e4306d94eb1392d7400a80143621"

  cluster_name = local.cluster_name
  namespace    = "kube-system"

  create_pod_identity_association = true

  # The controller policy is longer than the 6,144-character limit for
  # managed IAM policies; inline role policies allow 10,240.
  enable_inline_policy = true

  # Fixed name: the EC2NodeClass in gitops/ and the destroy workflow use it
  node_iam_role_use_name_prefix = false
  node_iam_role_name            = "${local.cluster_name}-karpenter-node"

  # Shell into nodes with SSM Session Manager - no SSH keys or open ports
  node_iam_role_additional_policies = {
    AmazonSSMManagedInstanceCore = "arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore"
  }
}

# -----------------------------------------------------------------------------
# Karpenter - cluster side. The CRDs are their own release because Helm never
# upgrades CRDs bundled inside a chart; a dedicated CRD chart can be upgraded.
# -----------------------------------------------------------------------------
resource "helm_release" "karpenter_crd" {
  name       = "karpenter-crd"
  namespace  = "kube-system"
  repository = "oci://public.ecr.aws/karpenter"
  chart      = "karpenter-crd"
  version    = var.karpenter_version
}

resource "helm_release" "karpenter" {
  name       = "karpenter"
  namespace  = "kube-system"
  repository = "oci://public.ecr.aws/karpenter"
  chart      = "karpenter"
  version    = var.karpenter_version
  skip_crds  = true
  wait       = true

  values = [yamlencode({
    settings = {
      clusterName       = local.cluster_name
      clusterEndpoint   = local.cluster_endpoint
      interruptionQueue = module.karpenter.queue_name
    }

    serviceAccount = {
      name = module.karpenter.service_account
    }

    nodeSelector = local.system_node_selector

    # Start without depending on in-cluster DNS (CoreDNS)
    dnsPolicy = "Default"

    controller = {
      resources = {
        requests = { cpu = "250m", memory = "512Mi" }
        limits   = { memory = "512Mi" }
      }
    }
  })]

  depends_on = [
    helm_release.karpenter_crd,
    module.karpenter,
  ]
}
