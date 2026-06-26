"""
AGNTCY Mortgage Underwriting Pipeline
7-agent orchestration: Application Processor → [Credit Analyzer ‖ Collateral Valuator ‖ Compliance Checker]
→ Risk Scorer → Decision Engine → Documentation Generator
"""
from __future__ import annotations
import json
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

from agents.llm_provider import call_llm, parse_json_response
from ml.models import predict_credit_risk, predict_fraud_risk
from protocols.emitter import ProtocolEmitter, PipelineContext


# ─── Data types ───────────────────────────────────────────────────────────────

@dataclass
class AgentResult:
    agent_id: str
    agent_name: str
    status: str          # "completed" | "failed"
    started_at: float
    completed_at: float
    duration_ms: int
    input_data: dict
    output_data: dict
    error: str | None = None


@dataclass
class PipelineRun:
    application_id: str
    session_id: str
    trace_id: str
    started_at: float
    completed_at: float | None
    status: str          # "running" | "completed" | "failed"
    agent_results: list[AgentResult] = field(default_factory=list)
    slim_messages: list[dict] = field(default_factory=list)
    otel_spans: list[dict] = field(default_factory=list)
    dir_events: list[dict] = field(default_factory=list)
    final_decision: dict | None = None


# ─── Agent registry ───────────────────────────────────────────────────────────

AGENTS = {
    "application-processor": {
        "name": "Application Processor",
        "version": "1.2.0",
        "did": "did:agntcy:mortgage:application-processor",
        "capabilities": ["document_validation", "data_extraction", "completeness_check"],
        "pipeline_stage": "intake",
        "execution_mode": "sequential",
    },
    "credit-analyzer": {
        "name": "Credit Analyzer",
        "version": "2.1.0",
        "did": "did:agntcy:mortgage:credit-analyzer",
        "capabilities": ["credit_scoring", "dti_analysis", "employment_verification"],
        "pipeline_stage": "parallel_analysis",
        "execution_mode": "parallel",
    },
    "collateral-valuator": {
        "name": "Collateral Valuator",
        "version": "1.8.0",
        "did": "did:agntcy:mortgage:collateral-valuator",
        "capabilities": ["property_valuation", "ltv_calculation", "market_analysis"],
        "pipeline_stage": "parallel_analysis",
        "execution_mode": "parallel",
    },
    "compliance-checker": {
        "name": "Compliance Checker",
        "version": "3.0.1",
        "did": "did:agntcy:mortgage:compliance-checker",
        "capabilities": ["fair_lending", "bsa_aml_screening", "regulatory_validation"],
        "pipeline_stage": "parallel_analysis",
        "execution_mode": "parallel",
    },
    "risk-scorer": {
        "name": "Risk Scorer",
        "version": "2.4.0",
        "did": "did:agntcy:mortgage:risk-scorer",
        "capabilities": ["composite_risk_scoring", "ml_ensemble", "risk_tiering"],
        "pipeline_stage": "aggregation",
        "execution_mode": "sequential",
    },
    "decision-engine": {
        "name": "Decision Engine",
        "version": "4.1.0",
        "did": "did:agntcy:mortgage:decision-engine",
        "capabilities": ["underwriting_decision", "rate_pricing", "condition_generation"],
        "pipeline_stage": "decision",
        "execution_mode": "sequential",
    },
    "documentation-generator": {
        "name": "Documentation Generator",
        "version": "1.5.0",
        "did": "did:agntcy:mortgage:documentation-generator",
        "capabilities": ["disclosure_generation", "adverse_action_notice", "loan_estimate"],
        "pipeline_stage": "output",
        "execution_mode": "sequential",
    },
}


# ─── Individual agent runners ─────────────────────────────────────────────────

def _run_agent(
    agent_id: str,
    input_data: dict,
    system_prompt: str,
    user_prompt: str,
    response_schema: dict,
    ctx: PipelineContext,
    settings: dict,
    parent_span_id: str | None = None,
) -> AgentResult:
    agent = AGENTS[agent_id]
    span_id = str(uuid.uuid4())[:8]
    started_at = time.time()

    # Emit DIR discovery event
    ctx.emitter.emit_dir_event(
        ctx, agent_id, agent["did"],
        event_type="DISCOVER",
        query_capability=agent["capabilities"][0],
        matched_agents=1,
        identity_verified=True,
    )

    # Emit SLIM request message
    ctx.emitter.emit_slim_message(
        ctx,
        from_agent="orchestrator",
        to_agent=agent_id,
        message_type="REQUEST",
        payload=input_data,
        pattern="request-reply",
    )

    # Emit OTel span start
    ctx.emitter.start_span(ctx, span_id, agent_id, parent_span_id)

    try:
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]
        raw = call_llm(messages, response_schema=response_schema, settings=settings)
        output = parse_json_response(raw)
        status = "completed"
        error = None
    except Exception as e:
        output = {}
        status = "failed"
        error = str(e)

    completed_at = time.time()
    duration_ms = int((completed_at - started_at) * 1000)

    # Emit SLIM response
    ctx.emitter.emit_slim_message(
        ctx,
        from_agent=agent_id,
        to_agent="orchestrator",
        message_type="RESPONSE",
        payload=output,
        pattern="request-reply",
        latency_ms=duration_ms,
    )

    # Emit OTel span end
    ctx.emitter.end_span(ctx, span_id, duration_ms, status, error)

    return AgentResult(
        agent_id=agent_id,
        agent_name=agent["name"],
        status=status,
        started_at=started_at,
        completed_at=completed_at,
        duration_ms=duration_ms,
        input_data=input_data,
        output_data=output,
        error=error,
    )


# ─── Agent 1: Application Processor ──────────────────────────────────────────

def run_application_processor(app: dict, ctx: PipelineContext, settings: dict) -> AgentResult:
    system = """You are the Application Processor agent in the AGNTCY mortgage underwriting pipeline.
Your role is to validate, normalize, and assess the completeness of mortgage loan applications.
Always respond with valid JSON matching the schema exactly."""

    user = f"""Process this mortgage application and return a structured assessment:

Application Data:
{json.dumps(app, indent=2)}

Return JSON with:
- applicationId: string (use the provided ID)
- borrowerProfile: {{name, creditScore, annualIncome, employmentStatus, employmentYears, debtToIncomeRatio}}
- loanRequest: {{amount, purpose, term, propertyValue, propertyType, propertyAddress}}
- completenessScore: number 0-100
- missingFields: array of strings
- dataQuality: "excellent"|"good"|"fair"|"poor"
- processingNotes: string
- readyForUnderwriting: boolean"""

    schema = {
        "type": "object",
        "properties": {
            "applicationId": {"type": "string"},
            "borrowerProfile": {"type": "object"},
            "loanRequest": {"type": "object"},
            "completenessScore": {"type": "number"},
            "missingFields": {"type": "array", "items": {"type": "string"}},
            "dataQuality": {"type": "string"},
            "processingNotes": {"type": "string"},
            "readyForUnderwriting": {"type": "boolean"},
        },
        "required": ["applicationId", "borrowerProfile", "loanRequest", "completenessScore",
                     "dataQuality", "processingNotes", "readyForUnderwriting"],
    }

    return _run_agent("application-processor", app, system, user, schema, ctx, settings)


# ─── Agent 2: Credit Analyzer ─────────────────────────────────────────────────

def run_credit_analyzer(app: dict, ctx: PipelineContext, settings: dict) -> AgentResult:
    # Pre-compute with XGBoost ML model
    ml_result = {}
    try:
        ml_result = predict_credit_risk(
            credit_score=float(app.get("creditScore", 700)),
            annual_income=float(app.get("annualIncome", 80000)),
            loan_amount=float(app.get("loanAmount", 300000)),
            property_value=float(app.get("propertyValue", 400000)),
            employment_years=float(app.get("employmentYears", 5)),
            is_self_employed=app.get("employmentStatus", "").lower() in ["self-employed", "self_employed"],
            geographic_risk=float(app.get("geographicRisk", 0.3)),
        )
    except Exception as e:
        ml_result = {"error": str(e)}

    system = """You are the Credit Analyzer agent in the AGNTCY mortgage underwriting pipeline.
You have access to XGBoost ML model predictions for probability of default.
Provide a comprehensive credit assessment. Always respond with valid JSON."""

    user = f"""Analyze the creditworthiness of this mortgage applicant.

Application Data:
{json.dumps(app, indent=2)}

XGBoost ML Model Prediction:
{json.dumps(ml_result, indent=2)}

Return JSON with:
- creditRating: "Excellent"|"Good"|"Fair"|"Poor"
- creditScore: number
- probabilityOfDefault: number (0-1, use ML model value)
- mlCreditRiskScore: number (0-100, from ML model)
- mlModelUsed: "XGBoost"
- dtiRatio: number
- dtiAssessment: "Low"|"Moderate"|"High"|"Very High"
- employmentStability: "Stable"|"Moderate"|"Unstable"
- keyStrengths: array of strings
- keyRisks: array of strings
- creditRecommendation: "Approve"|"Conditional"|"Decline"
- analysisNotes: string"""

    schema = {
        "type": "object",
        "properties": {
            "creditRating": {"type": "string"},
            "creditScore": {"type": "number"},
            "probabilityOfDefault": {"type": "number"},
            "mlCreditRiskScore": {"type": "number"},
            "mlModelUsed": {"type": "string"},
            "dtiRatio": {"type": "number"},
            "dtiAssessment": {"type": "string"},
            "employmentStability": {"type": "string"},
            "keyStrengths": {"type": "array", "items": {"type": "string"}},
            "keyRisks": {"type": "array", "items": {"type": "string"}},
            "creditRecommendation": {"type": "string"},
            "analysisNotes": {"type": "string"},
        },
        "required": ["creditRating", "creditScore", "probabilityOfDefault", "mlCreditRiskScore",
                     "mlModelUsed", "dtiRatio", "dtiAssessment", "employmentStability",
                     "keyStrengths", "keyRisks", "creditRecommendation", "analysisNotes"],
    }

    input_data = {**app, "mlPrediction": ml_result}
    return _run_agent("credit-analyzer", input_data, system, user, schema, ctx, settings)


# ─── Agent 3: Collateral Valuator ─────────────────────────────────────────────

def run_collateral_valuator(app: dict, ctx: PipelineContext, settings: dict) -> AgentResult:
    loan_amount = float(app.get("loanAmount", 300000))
    property_value = float(app.get("propertyValue", 400000))
    ltv = round(loan_amount / max(property_value, 1) * 100, 2)

    system = """You are the Collateral Valuator agent in the AGNTCY mortgage underwriting pipeline.
Assess property value, LTV ratio, and collateral risk. Always respond with valid JSON."""

    user = f"""Evaluate the collateral for this mortgage application.

Application Data:
{json.dumps(app, indent=2)}

Pre-computed LTV: {ltv}%

Return JSON with:
- propertyType: string
- estimatedValue: number
- ltvRatio: number (percentage)
- ltvAssessment: "Low Risk"|"Moderate Risk"|"High Risk"|"Very High Risk"
- propertyCondition: "Excellent"|"Good"|"Fair"|"Poor"
- marketTrend: "Appreciating"|"Stable"|"Declining"
- collateralAdequacy: "Adequate"|"Marginal"|"Insufficient"
- appraisalNotes: string
- collateralRecommendation: "Approve"|"Conditional"|"Decline" """

    schema = {
        "type": "object",
        "properties": {
            "propertyType": {"type": "string"},
            "estimatedValue": {"type": "number"},
            "ltvRatio": {"type": "number"},
            "ltvAssessment": {"type": "string"},
            "propertyCondition": {"type": "string"},
            "marketTrend": {"type": "string"},
            "collateralAdequacy": {"type": "string"},
            "appraisalNotes": {"type": "string"},
            "collateralRecommendation": {"type": "string"},
        },
        "required": ["propertyType", "estimatedValue", "ltvRatio", "ltvAssessment",
                     "propertyCondition", "marketTrend", "collateralAdequacy",
                     "appraisalNotes", "collateralRecommendation"],
    }

    input_data = {**app, "preComputedLtv": ltv}
    return _run_agent("collateral-valuator", input_data, system, user, schema, ctx, settings)


# ─── Agent 4: Compliance Checker ──────────────────────────────────────────────

def run_compliance_checker(app: dict, ctx: PipelineContext, settings: dict) -> AgentResult:
    # GNN fraud risk
    gnn_result = {}
    try:
        gnn_result = predict_fraud_risk(
            credit_score=float(app.get("creditScore", 700)),
            annual_income=float(app.get("annualIncome", 80000)),
            loan_amount=float(app.get("loanAmount", 300000)),
            property_value=float(app.get("propertyValue", 400000)),
            employment_years=float(app.get("employmentYears", 5)),
            is_self_employed=app.get("employmentStatus", "").lower() in ["self-employed", "self_employed"],
            geographic_risk=float(app.get("geographicRisk", 0.5)),
        )
    except Exception as e:
        gnn_result = {"error": str(e)}

    system = """You are the Compliance Checker agent in the AGNTCY mortgage underwriting pipeline.
You have access to GNN (Graph Neural Network) fraud detection scores.
Check Fair Lending, BSA/AML, and regulatory compliance. Always respond with valid JSON."""

    user = f"""Perform compliance screening for this mortgage application.

Application Data:
{json.dumps(app, indent=2)}

GNN Fraud Detection Score:
{json.dumps(gnn_result, indent=2)}

Return JSON with:
- fairLendingResult: "Pass"|"Review"|"Fail"
- fairLendingFindings: array of strings
- bsaAmlResult: "Clear"|"Review"|"Flag"
- bsaAmlFindings: array of strings
- gnnFraudScore: number (0-100, from GNN model)
- gnnModelUsed: "GNN (2-layer GCN)"
- fraudRiskLevel: "Low"|"Medium"|"High"
- regulatoryChecks: {{ltvCompliant: boolean, dtiCompliant: boolean, creditScoreCompliant: boolean}}
- requiredDisclosures: array of strings
- overallComplianceStatus: "Pass"|"Review"|"Fail"
- complianceNotes: string"""

    schema = {
        "type": "object",
        "properties": {
            "fairLendingResult": {"type": "string"},
            "fairLendingFindings": {"type": "array", "items": {"type": "string"}},
            "bsaAmlResult": {"type": "string"},
            "bsaAmlFindings": {"type": "array", "items": {"type": "string"}},
            "gnnFraudScore": {"type": "number"},
            "gnnModelUsed": {"type": "string"},
            "fraudRiskLevel": {"type": "string"},
            "regulatoryChecks": {"type": "object"},
            "requiredDisclosures": {"type": "array", "items": {"type": "string"}},
            "overallComplianceStatus": {"type": "string"},
            "complianceNotes": {"type": "string"},
        },
        "required": ["fairLendingResult", "bsaAmlResult", "gnnFraudScore", "gnnModelUsed",
                     "fraudRiskLevel", "regulatoryChecks", "overallComplianceStatus", "complianceNotes"],
    }

    input_data = {**app, "gnnPrediction": gnn_result}
    return _run_agent("compliance-checker", input_data, system, user, schema, ctx, settings)


# ─── Agent 5: Risk Scorer ─────────────────────────────────────────────────────

def run_risk_scorer(
    app: dict,
    credit_result: dict,
    collateral_result: dict,
    compliance_result: dict,
    ctx: PipelineContext,
    settings: dict,
) -> AgentResult:
    system = """You are the Risk Scorer agent in the AGNTCY mortgage underwriting pipeline.
Aggregate outputs from Credit Analyzer, Collateral Valuator, and Compliance Checker into a composite risk score.
Always respond with valid JSON."""

    user = f"""Compute a composite risk score from the parallel agent outputs.

Original Application:
{json.dumps(app, indent=2)}

Credit Analysis Result:
{json.dumps(credit_result, indent=2)}

Collateral Valuation Result:
{json.dumps(collateral_result, indent=2)}

Compliance Check Result:
{json.dumps(compliance_result, indent=2)}

Return JSON with:
- compositeRiskScore: number 0-100 (higher = lower risk)
- riskTier: "Tier 1 - Prime"|"Tier 2 - Near Prime"|"Tier 3 - Subprime"|"Tier 4 - High Risk"
- creditWeight: number (contribution 0-1)
- collateralWeight: number (contribution 0-1)
- complianceWeight: number (contribution 0-1)
- mlEnsembleScore: number (weighted average of XGBoost + GNN scores)
- riskFactors: array of strings (top risk factors)
- mitigatingFactors: array of strings
- recommendedAction: "Approve"|"Conditional Approval"|"Decline"
- scoringNotes: string"""

    schema = {
        "type": "object",
        "properties": {
            "compositeRiskScore": {"type": "number"},
            "riskTier": {"type": "string"},
            "creditWeight": {"type": "number"},
            "collateralWeight": {"type": "number"},
            "complianceWeight": {"type": "number"},
            "mlEnsembleScore": {"type": "number"},
            "riskFactors": {"type": "array", "items": {"type": "string"}},
            "mitigatingFactors": {"type": "array", "items": {"type": "string"}},
            "recommendedAction": {"type": "string"},
            "scoringNotes": {"type": "string"},
        },
        "required": ["compositeRiskScore", "riskTier", "mlEnsembleScore",
                     "riskFactors", "mitigatingFactors", "recommendedAction", "scoringNotes"],
    }

    input_data = {
        "application": app,
        "creditAnalysis": credit_result,
        "collateralValuation": collateral_result,
        "complianceCheck": compliance_result,
    }
    return _run_agent("risk-scorer", input_data, system, user, schema, ctx, settings)


# ─── Agent 6: Decision Engine ─────────────────────────────────────────────────

def run_decision_engine(
    app: dict,
    risk_result: dict,
    credit_result: dict,
    compliance_result: dict,
    ctx: PipelineContext,
    settings: dict,
) -> AgentResult:
    system = """You are the Decision Engine agent in the AGNTCY mortgage underwriting pipeline.
Make the final underwriting decision with full explainability.
Always respond with valid JSON."""

    user = f"""Make the final underwriting decision for this mortgage application.

Application:
{json.dumps(app, indent=2)}

Risk Score:
{json.dumps(risk_result, indent=2)}

Credit Analysis:
{json.dumps(credit_result, indent=2)}

Compliance:
{json.dumps(compliance_result, indent=2)}

Return JSON with:
- decision: "Approved"|"Conditional Approval"|"Denied"
- decisionConfidence: number 0-100
- interestRate: number (percentage, e.g. 6.75)
- loanTerm: number (years)
- approvedAmount: number
- conditions: array of strings (empty if approved outright)
- decisionFactors: array of {{factor: string, impact: "Positive"|"Negative"|"Neutral", weight: number}}
- adverseActionReasons: array of strings (empty if approved)
- expiryDays: number (how long offer is valid)
- decisionSummary: string"""

    schema = {
        "type": "object",
        "properties": {
            "decision": {"type": "string"},
            "decisionConfidence": {"type": "number"},
            "interestRate": {"type": "number"},
            "loanTerm": {"type": "number"},
            "approvedAmount": {"type": "number"},
            "conditions": {"type": "array", "items": {"type": "string"}},
            "decisionFactors": {"type": "array"},
            "adverseActionReasons": {"type": "array", "items": {"type": "string"}},
            "expiryDays": {"type": "number"},
            "decisionSummary": {"type": "string"},
        },
        "required": ["decision", "decisionConfidence", "interestRate", "loanTerm",
                     "approvedAmount", "conditions", "decisionFactors",
                     "adverseActionReasons", "expiryDays", "decisionSummary"],
    }

    input_data = {
        "application": app,
        "riskScore": risk_result,
        "creditAnalysis": credit_result,
        "complianceCheck": compliance_result,
    }
    return _run_agent("decision-engine", input_data, system, user, schema, ctx, settings)


# ─── Agent 7: Documentation Generator ────────────────────────────────────────

def run_documentation_generator(
    app: dict,
    decision_result: dict,
    compliance_result: dict,
    ctx: PipelineContext,
    settings: dict,
) -> AgentResult:
    system = """You are the Documentation Generator agent in the AGNTCY mortgage underwriting pipeline.
Generate all required regulatory disclosures and loan documents.
Always respond with valid JSON."""

    user = f"""Generate required mortgage documentation for this decision.

Application:
{json.dumps(app, indent=2)}

Decision:
{json.dumps(decision_result, indent=2)}

Compliance:
{json.dumps(compliance_result, indent=2)}

Return JSON with:
- loanEstimate: {{apr: number, monthlyPayment: number, totalInterest: number, closingCosts: number}}
- requiredDisclosures: array of {{name: string, status: "Generated"|"Required", description: string}}
- adverseActionNotice: string or null
- documentationComplete: boolean
- nextSteps: array of strings
- documentNotes: string"""

    schema = {
        "type": "object",
        "properties": {
            "loanEstimate": {"type": "object"},
            "requiredDisclosures": {"type": "array"},
            "adverseActionNotice": {},
            "documentationComplete": {"type": "boolean"},
            "nextSteps": {"type": "array", "items": {"type": "string"}},
            "documentNotes": {"type": "string"},
        },
        "required": ["loanEstimate", "requiredDisclosures", "documentationComplete",
                     "nextSteps", "documentNotes"],
    }

    input_data = {
        "application": app,
        "decision": decision_result,
        "compliance": compliance_result,
    }
    return _run_agent("documentation-generator", input_data, system, user, schema, ctx, settings)


# ─── Main orchestrator ────────────────────────────────────────────────────────

def run_pipeline(application: dict, settings: dict, progress_callback=None) -> PipelineRun:
    """
    Run the full 7-agent mortgage underwriting pipeline.
    progress_callback(step: int, total: int, message: str) is called at each step.
    """
    from protocols.emitter import ProtocolEmitter, PipelineContext

    session_id = str(uuid.uuid4())
    trace_id = str(uuid.uuid4())
    emitter = ProtocolEmitter()
    ctx = PipelineContext(
        session_id=session_id,
        trace_id=trace_id,
        application_id=application.get("applicationId", str(uuid.uuid4())[:8]),
        emitter=emitter,
    )

    run = PipelineRun(
        application_id=ctx.application_id,
        session_id=session_id,
        trace_id=trace_id,
        started_at=time.time(),
        completed_at=None,
        status="running",
    )

    total_steps = 7

    def _progress(step: int, msg: str):
        if progress_callback:
            progress_callback(step, total_steps, msg)

    try:
        # Step 1: Application Processor
        _progress(1, "Application Processor — validating input...")
        r1 = run_application_processor(application, ctx, settings)
        run.agent_results.append(r1)

        # Steps 2-4: Parallel analysis
        _progress(2, "Credit Analyzer — running XGBoost model...")
        r2 = run_credit_analyzer(application, ctx, settings)
        run.agent_results.append(r2)

        _progress(3, "Collateral Valuator — assessing property...")
        r3 = run_collateral_valuator(application, ctx, settings)
        run.agent_results.append(r3)

        _progress(4, "Compliance Checker — running GNN fraud detection...")
        r4 = run_compliance_checker(application, ctx, settings)
        run.agent_results.append(r4)

        # Step 5: Risk Scorer
        _progress(5, "Risk Scorer — computing composite risk score...")
        r5 = run_risk_scorer(
            application,
            r2.output_data, r3.output_data, r4.output_data,
            ctx, settings,
        )
        run.agent_results.append(r5)

        # Step 6: Decision Engine
        _progress(6, "Decision Engine — making underwriting decision...")
        r6 = run_decision_engine(
            application,
            r5.output_data, r2.output_data, r4.output_data,
            ctx, settings,
        )
        run.agent_results.append(r6)

        # Step 7: Documentation Generator
        _progress(7, "Documentation Generator — generating disclosures...")
        r7 = run_documentation_generator(
            application, r6.output_data, r4.output_data,
            ctx, settings,
        )
        run.agent_results.append(r7)

        run.final_decision = r6.output_data
        run.status = "completed"

    except Exception as e:
        run.status = "failed"
        run.final_decision = {"error": str(e)}

    run.completed_at = time.time()
    run.slim_messages = emitter.slim_messages
    run.otel_spans = emitter.otel_spans
    run.dir_events = emitter.dir_events

    return run
