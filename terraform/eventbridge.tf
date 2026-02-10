# EventBridge rule to trigger calculator Lambda hourly
resource "aws_cloudwatch_event_rule" "calculator_hourly" {
  name                = "aztec-supply-calculator-hourly"
  description         = "Trigger Aztec supply calculator every hour"
  schedule_expression = "rate(1 hour)"
}

# Target the calculator Lambda
resource "aws_cloudwatch_event_target" "calculator" {
  rule      = aws_cloudwatch_event_rule.calculator_hourly.name
  target_id = "CalculatorLambda"
  arn       = aws_lambda_function.calculator.arn
}

# Lambda permission for EventBridge to invoke calculator
resource "aws_lambda_permission" "eventbridge_calculator" {
  statement_id  = "AllowEventBridgeInvoke"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.calculator.function_name
  principal     = "events.amazonaws.com"
  source_arn    = aws_cloudwatch_event_rule.calculator_hourly.arn
}
