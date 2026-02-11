# Route53 A record for supply.aztec.network -> CloudFront
resource "aws_route53_record" "supply" {
  zone_id = var.route53_zone_id
  name    = local.domain_name
  type    = "A"

  alias {
    name                   = aws_cloudfront_distribution.supply.domain_name
    zone_id                = aws_cloudfront_distribution.supply.hosted_zone_id
    evaluate_target_health = false
  }
}

# AAAA record for IPv6
resource "aws_route53_record" "supply_ipv6" {
  zone_id = var.route53_zone_id
  name    = local.domain_name
  type    = "AAAA"

  alias {
    name                   = aws_cloudfront_distribution.supply.domain_name
    zone_id                = aws_cloudfront_distribution.supply.hosted_zone_id
    evaluate_target_health = false
  }
}
