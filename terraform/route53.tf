# Route53 A record for supply.aztec.network
resource "aws_route53_record" "supply" {
  zone_id = var.route53_zone_id
  name    = local.domain_name
  type    = "A"

  alias {
    name                   = aws_apigatewayv2_domain_name.supply.domain_name_configuration[0].target_domain_name
    zone_id                = aws_apigatewayv2_domain_name.supply.domain_name_configuration[0].hosted_zone_id
    evaluate_target_health = false
  }
}
