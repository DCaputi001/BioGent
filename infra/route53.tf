# route53.tf
# DNS for the custom domain (biogent.io / www.biogent.io), purchased through
# Route 53 Registrar, which created this hosted zone automatically at
# purchase time.
#
# The zone itself is a data source, not a resource. Terraform must never be
# able to destroy it -- that would tear down the domain's nameserver
# delegation, not just some records inside it. Only the specific alias
# records this app owns are declared as managed resources, imported rather
# than created (see infra/README.md), so nothing here was ever deleted and
# recreated.
#
# "biogent.io." is a plain literal rather than derived from
# custom_domain_names: both domains live in this one zone, and this repo
# already hardcodes other deployment-specific facts the same way (the AWS
# account id in versions.tf's state backend).

data "aws_route53_zone" "biogent" {
  name         = "biogent.io."
  private_zone = false
}

resource "aws_route53_record" "apex" {
  for_each = toset(var.custom_domain_names)

  zone_id = data.aws_route53_zone.biogent.id
  name    = each.value
  type    = "A"

  alias {
    name = aws_cloudfront_distribution.main.domain_name
    # CloudFront's fixed alias hosted-zone id -- the same value for every
    # CloudFront distribution, in every AWS account. Not this account's id.
    zone_id                = "Z2FDTNDATAQYW2"
    evaluate_target_health = false
  }
}

resource "aws_route53_record" "apex_ipv6" {
  for_each = toset(var.custom_domain_names)

  zone_id = data.aws_route53_zone.biogent.id
  name    = each.value
  type    = "AAAA"

  alias {
    name                   = aws_cloudfront_distribution.main.domain_name
    zone_id                = "Z2FDTNDATAQYW2"
    evaluate_target_health = false
  }
}
