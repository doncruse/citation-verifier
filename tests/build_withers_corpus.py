"""Build a structured proposition-assessment corpus from the Withers v. City of
Aberdeen citation-audit exhibit.

Source (canonical): tests/data/withers_aberdeen/exhibit1_doc112-1.pdf —
Exhibit 1 to Doc. 112-1 in Withers v. City of Aberdeen, No. 1:24-cv-00218-SA-RP
(N.D. Miss., filed 12/24/2025). A party-authored, citation-by-citation audit of
the plaintiff's (apparently AI-assisted) filings, color-coded:
  green  = case exists AND broadly supports the proposition (ok)
  yellow = case exists BUT the proposition/quote has a problem (overstated,
           misquoted, wrong court, wrong pincite, unsupported)
  red    = case does not exist / hallucinated

This maps 1:1 onto the verifier's two layers:
  "Does it Exist?"  ~ the verifier   (NOT_FOUND / WRONG_CASE / CITE_UNCONFIRMED)
  color + Irregularity ~ the assessment (Green / Yellow / Red)

Two reds (City of Grenada v. Harrelson; Crittendon v. State Farm) are already in
tests/data/charlotin_corpus.json, sourced from this same case (the court's
findings on the Doc. 105 opposition) — a cross-validation anchor.

PROVENANCE NOTE: the `proposition` and `irregularity` text is transcribed by hand
from the rendered PDF table; the committed PDF is authoritative if any cell is in
doubt. `exists` and `label` are reliable (the color + Yes/No are unambiguous).
`hedged=True` marks rows whose Irregularity is explicitly tentative ("arguable",
"debatable", "seems", "appears", "I believe", "a bit confusing") — the author's
own judgment is uncertain there, so the green/yellow call is soft.

Run: venv/Scripts/python.exe tests/build_withers_corpus.py
Output: tests/data/withers_aberdeen_corpus.csv
"""
from __future__ import annotations

import csv
from pathlib import Path

# Each row: (doc, pleading_short, citation, proposition, exists, label, hedged, irregularity)
# pleading_short codes:
#   disqualify   = Motion / Memo to Disqualify Counsel (Doc 48/50)
#   excus_neglect= Memo ISO Opp. to Mot. for Leave to File Out of Time (Doc 65)
#   msj_admis    = Mot. for SJ for Failure to Respond to RFAs (Doc 72)
#   reply_36b    = Reply ISO MSJ / Opp. to Rule 36(b)/6(b)(1)(B) relief (Doc 81)
#   compel       = Mot. to Compel Discovery Responses (Doc 86)
#   rule72a      = Rule 72(a) Objection to Mag. Order Setting Aside Default (Doc 96)
#   atty_fees    = Memo in Opp. to Mot. Challenging Reasonableness of Atty Fees (Doc 102)
#   opp_msj      = Withers Opp. to City MSJ (Doc 105)
#   surreply     = Mot. for Leave to File Surreply (Doc 108)
#   resp_surreply= (Proposed) Response to Defendant's Sur-Reply (Doc 108-1)

ROWS = [
    # ---- page 1 (PageID 513) ----
    ("48", "disqualify", "Nix v. Whiteside, 475 U.S. 157, 166 (1986).",
     "Courts have consistently recognized that the purpose of the rules governing conflicts of interest is not only to protect the interests of clients but also to maintain the integrity of the judicial process.",
     "Yes", "green", False,
     "The citation should include \"See\" as an introductory signal, but the case does broadly stand for the proposition stated."),
    ("50", "disqualify", "Nix v. Whiteside, 475 U.S. 157, 166 (1986).",
     "Courts have consistently recognized that the purpose of the rules governing conflicts of interest is not only to protect the interests of clients but also to maintain the integrity of the judicial process.",
     "Yes", "green", False,
     "The citation should include \"See\" as an introductory signal, but the case does broadly stand for the proposition stated. Note this is a similar, but not identical, filing as Doc. 48. For this reason, we included it as a separate entry."),
    ("65", "excus_neglect", "Pioneer Inv. Servs. Co. v. Brunswick Assocs. Ltd. P'ship, 507 U.S. 380, 395 (1993).",
     "The Supreme Court has established that the determination of \"excusable neglect\" is \"an equitable one, taking account of all relevant circumstances surrounding the party's omission,\" including: the danger of prejudice to the debtor, the length of the delay and its potential impact on judicial proceedings, the reason for the delay, including whether it was within the reasonable control of the movant, and whether the movant acted in good faith.",
     "Yes", "green", False, "None."),
    ("65", "excus_neglect", "Midwest Employers Cas. Co. v. Williams, 161 F.3d 877, 879 (5th Cir. 1998).",
     "The Fifth Circuit has consistently held that \"the excusable neglect standard is a strict one\" and that \"inadvertence, ignorance of the rules, or mistakes construing the rules do not usually constitute excusable neglect.\"",
     "Yes", "yellow", False,
     "The citation does provide the quotation: \"inadvertence, ignorance of the rules, or mistakes construing the rules do not usually constitute excusable neglect.\" It does not, however, contain the initial quoted language: \"the excusable neglect standard is a strict one,\" although it can be argued the case generally supports the proposition. Furthermore, additional Fifth Circuit citations provide the correct quotation. See Birl v. Estelle, 660 F.2d 592, 593 (5th Cir. 1981)."),
    ("65", "excus_neglect", "Silvercreek Mgmt., Inc. v. Banc of Am. Sec., LLC, 534 F.3d 469, 472 (5th Cir. 2008).",
     "The Fifth Circuit has consistently held that delays within a party's control do not constitute excusable neglect.",
     "Yes", "yellow", False,
     "The court's holding was slightly narrower than the stated proposition. It held the party's failure to file a Fed. R. Civ. P. 4(a)(1) notice of appeal on time was not excusable neglect because counsel could have determined the correct opt-out date on their own accord. See id. at 472-73."),
    ("65", "excus_neglect", "Wilkens v. Johnson, 238 F.3d 328 (5th Cir. 2001).",
     "Wilkens involved unique circumstances not present here, including a pro se litigant and confusion regarding the application of the prison mailbox rule.",
     "Yes", "yellow", False,
     "This case did not involve a pro se litigant or the prison mailbox rule. Rather, the issue was whether the appellant's counsel's receipt of a written facsimile copy of judgment was sufficient to start the 7-day clock for appeal, even if not served by mail from the court in strict compliance with Fed. R. Civ. P. 77(d). See id. at 333-34."),
    ("72", "msj_admis", "Celotex Corp. v. Catrett, 477 U.S. 317, 327 (1986).",
     "Summary judgment is a procedural tool designed to secure the \"just, speedy and inexpensive determination of every action.",
     "Yes", "green", False, "None."),
    ("72", "msj_admis", "Anderson v. Liberty Lobby, Inc., 477 U.S. 242, 248 (1986).",
     "(1) A fact is \"material\" if it might affect the outcome of the suit under the governing law. (2) A dispute is \"genuine\" if the evidence is such that a reasonable jury could return a verdict for the nonmoving party.",
     "Yes", "green", False, "None."),
    ("72", "msj_admis", "American Auto. Ass'n v. AAA Legal Clinic of Jefferson Crooke, 930 F.2d 1117, 1120 (5th Cir. 1991).",
     "Deemed admissions are \"judicial admissions\" that are binding on the party and cannot be contradicted at trial or on a motion for summary judgment.",
     "Yes", "yellow", False,
     "Although the case does not mention \"judicial admissions\" in those words, it does support the proposition admissions are binding and cannot be rebutted by contrary testimony."),
    ("72", "msj_admis", "Donovan v. Carls Drug Co., 703 F.2d 650, 652 (2d Cir. 1983).",
     "\"Admissions obtained under Rule 36, including those deemed admitted through a party's failure to respond, can form the basis for summary judgment.\"",
     "Yes", "yellow", False,
     "The case cited does not include the quotation provided."),
    # ---- page 2 (PageID 514) ----
    ("72", "msj_admis", "See, e.g., In re Carney, 258 F.3d 415, 420 (5th Cir. 2001).",
     "The Fifth Circuit has consistently upheld summary judgments based on deemed admissions.",
     "Yes", "green", False, "None."),
    ("81", "reply_36b", "American Auto. Ass'n v. AAA Legal Clinic of Jefferson Crooke, 930 F.2d 1117, 1120 (5th Cir. 1991).",
     "(1) Rule 36 is self-executing: the City's failure to timely serve written answers results in conclusive judicial admissions. The Fifth Circuit recognizes that deemed admissions are judicial admissions that may not be contradicted and can alone support summary judgment. (2) Admissions are binding and cannot be contradicted to avoid summary judgment.",
     "Yes", "yellow", False,
     "This case discusses a trial court's decision to permit the withdrawal or amendment of an admission, rather than failure to timely serve admissions and does not address the issue in light of the summary judgment standard. See id. at 1119-20. However, it does stand for the proposition admissions are binding and cannot be rebutted by contrary testimony."),
    ("81", "reply_36b", "Donovan v. Carls Drug Co., 703 F.2d 650, 652 (2d Cir. 1983).",
     "(1) The admissions establish every element for judgment. (2) The Fifth Circuit recognizes that deemed admissions are judicial admissions that may not be contradicted and can alone support summary judgment. (3) Deemed admissions are \"not mere evidence; they are conclusive judicial admissions\" and are fully competent to support summary judgment.",
     "Yes", "yellow", False,
     "This is a Second, not Fifth Circuit case. However, this case does support the proposition that summary judgment may stand where a party who is issued requests for admission fails to timely respond. (3) The cited quote is not present in the case."),
    ("81", "reply_36b", "In re Carney, 258 F.3d 415, 420 (5th Cir. 2001).",
     "(1) The admissions establish every element for judgment. (2) The Fifth Circuit recognizes that deemed admissions are judicial admissions that may not be contradicted and can alone support summary judgment. (3) Deemed admissions are \"not mere evidence; they are conclusive judicial admissions\" and are fully competent to support summary judgment. (4) The Fifth Circuit has explained that prejudice involves real impairment in obtaining evidence, not merely having to prove a case. (5) permitting a late, contested re-do after Plaintiff has relied on conclusive admissions to prosecute his case will derail efficiencies Rule 36 is designed to achieve and materially impair Plaintiff's ability to obtain and present evidence on a sensible schedule.",
     "Yes", "yellow", False,
     "Although it is unclear what is meant by a \"judicial admission,\" this case does support the proposition that summary judgment may stand where a party who is issued requests for admission fails to timely respond or move to withdraw or amend their deemed responses. (3) The cited quote is not present in the case. (4) This proposition is not supported by this case. (5) The case does not discuss Rule 36's \"efficiencies\" or prejudice to a party for failure to obtain discovery on a sensible schedule. However, it does broadly support strict compliance with Rule 36 and similar rules."),
    ("81", "reply_36b", "Celotex Corp. v. Catrett, 477 U.S. 317, 327 (1986).",
     "Defendant's \"deemed admissions\" eliminate any genuine dispute of material fact.",
     "Yes", "green", False,
     "None. Celotex establishes the general rule that the admissions on file, along with other evidence, may support a holding there is no genuine issue of material fact for summary judgment purposes."),
    ("81", "reply_36b", "Anderson v. Liberty Lobby, Inc., 477 U.S. 242, 248 (1986).",
     "Defendant's \"deemed admissions\" eliminate any genuine dispute of material fact.",
     "Yes", "green", False,
     "None. Anderson reiterates the Celotex rule that the admissions on file, along with other evidence, may support a holding there is no genuine issue of material fact for summary judgment purposes."),
    ("81", "reply_36b", "Pioneer Inv. Servs. Co. v. Brunswick Assocs. Ltd. P'ship, 507 U.S. 380, 395 (1993).",
     "Even if Rule 6(b)(1)(B) were properly invoked, the equitable factors weigh against the City: danger of prejudice, length of delay, reason for delay, and good faith.",
     "Yes", "green", False, "None."),
    # ---- page 3 (PageID 515) ----
    ("81", "reply_36b", "Adams v. Travelers Indem. Co. of Conn., 465 F.3d 156, 161 n.8 (5th Cir. 2006).",
     "Even if Rule 6(b)(1)(B) were properly invoked, the equitable factors weigh against the City: danger of prejudice, length of delay, reason for delay, and good faith.",
     "Yes", "green", False, "None."),
    ("81", "reply_36b", "Le v. Cheesecake Factory Rests. Inc., 2007 WL 715260, at *3 (5th Cir. Mar. 6, 2007).",
     "Le does not excuse a party's failure to serve and to promptly move for relief after default.",
     "Yes", "green", False, "None."),
    ("86", "compel", "See, e.g., In re United States, 864 F.2d 1153, 1156 (5th Cir. 1989).",
     "Defendant's failure to respond constitutes a waiver of any objections it might have asserted to Plaintiff's discovery requests.",
     "Yes", "green", False, "None."),
    ("96", "rule72a", "Lacy v. Sitel Corporation, 227 F.3d 290, 292 (5th Cir. 2000).",
     "(1) When determining whether to set aside default judgment, the Fifth Circuit directs courts to consider whether (1) the default was willful, (2) the non-defaulting party would be prejudiced, and (3) a meritorious defense has been presented. (2) willfulness turns on intentional failure to respond. (4) \"mere delay does not alone constitute prejudice,\" but prejudice exists where delay results \"in the loss of evidence, increased difficulties in discovery, or greater opportunities for fraud or collusion.\" (5) In short, it is not a \"defense sufficient to support a finding on the merits for the defaulting party.\"",
     "Yes", "green", False, "None."),
    ("96", "rule72a", "Dierschke v. O'Cheskey (In re Dierschke), 975 F.2d 181, 184 (5th Cir. 1992).",
     "(1) While the factors listed in Lacy are not \"rigid,\" their application is \"informed by equitable principles,\" and the \"meritorious defense\" component serves a gatekeeping function. (2) Fifth Circuit precedent acknowledges a \"universal[] favor\" for adjudication on the merits, but it also emphasizes that the Rule 55(c) decision is \"committed to the sound discretion of the trial court,\" bounded by the good-cause factors and equitable principles.",
     "Yes", "green", False, "None."),
    ("96", "rule72a", "Jenkens & Gilchrist v. Groia & Co., 542 F.3d 114, 122 (5th Cir. 2008).",
     "The Fifth Circuit has been unambiguous that a defendant must do more than offer conclusory denials; it must \"provide definite factual allegations, as opposed to mere legal conclusions, in support of [the] defense\" such that, \"if believed at trial, [they] would lead to a result contrary to that achieved by the default.\"",
     "Yes", "green", False, "None."),
    ("96", "rule72a", "Moldwood Corp. v. Stutts, 410 F.2d 351, 352 (5th Cir. 1969).",
     "A moving party's showing as to entitlement to relief from default must be \"clear and specific,\" \"not by conclusion, but by definite recitation of facts.\"",
     "Yes", "green", False, "None."),
    ("96", "rule72a", "In re OCA, Inc., 551 F.3d 359, 370 n.2 (5th Cir. 2008).",
     "The Fifth Circuit defines a \"willful\" default as an \"intentional failure to respond to litigation.\"",
     "Yes", "green", False,
     "None other than that the quoted portion can be found at n.32, not n.2."),
    # ---- page 4 (PageID 516) ----
    ("96", "rule72a", "Scott v. Carpanzano, 556 F. App'x 288, 295 (5th Cir. 2014).",
     "Scott v. Carpanzano is inopposite because there, the failure to answer reflected a single negligent omission.",
     "Yes", "green", True,
     "This is arguable. While this case reflects the appellant failed to meet only one procedural deadline, the court also notes (1) appellant's first attorney withdrew due to appellant's failure to cooperate and refusal to appear as requested and ordered, (2) appellant instructed his second set of attorneys to negotiate settlement but not file a NOA in court, (3) evidence suggested appellant and his attorneys were aware of the default proceeding for failure to answer, and (4) appellant ceased communication with his attorneys and did not finalize settlement. Therefore, it would be misleading to suggest failure to answer (a complaint, rather than RFAs) was the Court's only consideration."),
    ("96", "rule72a", "Berthelsen v. Kane, 907 F.2d 617, 621 (5th Cir. 1990).",
     "\"mere delay does not alone constitute prejudice,\" but prejudice exists where delay results \"in the loss of evidence, increased difficulties in discovery, or greater opportunities for fraud or collusion.\"",
     "Yes", "green", False,
     "None. This citation was used in a quote from the Lacey case, listed above, and not as authority for a separate assertion by the attorney for Plaintiff in this case."),
    ("96", "rule72a", "Gen. Tel. Corp. v. Gen. Tel. Answering Serv., 277 F.2d 919, 921 (5th Cir. 1960).",
     "Mere delay does not alone constitute prejudice, but prejudice exists where delay results in the loss of evidence, increased difficulties in discovery, or greater opportunities for fraud or collusion.",
     "Yes", "yellow", True,
     "This citation should have included a parenthetical explaining its relevance. Although the court briefly discusses a party's delay in filing a motion to set aside a default judgment, it does not discuss prejudice to a party or that prejudice exists where delay results in lost evidence, increased difficulty during discovery, or risks of fraud or collusion. In fact, in holding the trial court did not abuse its discretion in vacating a default judgment, it noted doing so does not harm the plaintiff other than to required plaintiff to prove its case. This seems to harm Plaintiff's argument in this Motion."),
    ("96", "rule72a", "Hernandez v. Hoolaulima Government Solutions, LLC, No. EP-23-CV-439-KC, 2024 WL 5274525, at *2 (W.D. Tex. Mar. 19, 2024).",
     "Nor can a fee award substitute for Rule 55(c)'s threshold requirements; it is a discretionary condition available once \"good cause\" is established, not a device to manufacture it.",
     "Yes", "green", False,
     "None. The case can also be found at: Hernandez v. Ho'Olaulima Gov't Sols., LLC, 2024 U.S. Dist. LEXIS 235864, *6 (W.D. Tex. March 19, 2024)."),
    ("96", "rule72a", "Rice v. HamiltonDavis Mental Health, Inc., No. 22-cv-397-TSL-RPM, 2023 WL 3746500, at *5 (S.D. Miss. May 31, 2023).",
     "Nor can a fee award substitute for Rule 55(c)'s threshold requirements; it is a discretionary condition available once \"good cause\" is established, not a device to manufacture it.",
     "Yes", "green", False,
     "None. This citation actually goes further to support the proposition, holding attorney's fees can be awarded even if \"good cause\" is not shown. The case can also be found at: Rice v. Hamiltondavis Mental Health, Inc., 2023 U.S. Dist. LEXIS 94373, *5 (S.D. Miss. May 31, 2023)."),
    ("102", "atty_fees", "Saizan v. Delta Concrete Prods. Co., 448 F.3d 795, 799 (5th Cir. 2006).",
     "The Fifth Circuit employs the lodestar method to calculate reasonable attorney's fees, which is the product of the number of hours reasonably expended multiplied by a reasonable hourly rate.",
     "Yes", "green", False,
     "This case states a slightly more narrow rule, but still broadly supports the proposition. This case provides that courts use the lodestar method, accurately recited in the proposition, to award attorneys fees in a Fair Labor Standards Act case."),
    ("102", "atty_fees", "McClain v. Lufkin Indus., Inc., 649 F.3d 374, 381 (5th Cir. 2011).",
     "While the prevailing rate in the district where the court sits is a key factor, it is not the only one in determining how much to award in attorney's fees.",
     "Yes", "yellow", True,
     "This is debatable. The authority provided generally holds that the \"forum rate\" or in-district rate is the starting point for calculating attorney fee awards but that out-of-district rates may be considered under certain circumstances. Thus, the use of the phrase \"key factor\" is slightly misleading."),
    # ---- page 5 (PageID 517) ----
    ("102", "atty_fees", "La. Power & Light Co. v. Kellstrom, 50 F.3d 319, 328 (5th Cir. 1995).",
     "An attorney's customary billing rate is presumptively reasonable. 'An attorney's requested hourly rate is prima facie reasonable when he requests a rate that is within the range of rates he has charged paying clients for similar work in the recent past.'",
     "Yes", "yellow", False,
     "This is misleading and an inaccurate quote. The correct quote is: \"When an attorney's customary billing rate is the rate at which the attorney requests the lodestar be computed and that rate is within the range of prevailing market rates, the court should consider this rate when fixing the hourly rate to be allowed. When that rate is not contested, it is prima facie reasonable. When the requested rate of compensation exceeds the attorney's usual charge but remains within the customary range in the community, the district court should consider whether the requested rate is reasonable.\" Thus, the authority does not support the proposition an attorney's hourly rate is prima facie reasonable when it is within the range he has charged clients for similar work."),
    ("102", "atty_fees", "See Jones et al v. Singing River Health Services Foundation et al, No. 1:2014cv00447 - Document 287 (S.D. Miss. 2016).",
     "This decision represents a fact-specific determination and does not establish a binding ceiling for all litigation in this District.",
     "Yes", "green", False,
     "This citation was used in Defendant's brief, which Plaintiff now distinguishes. The proposition is sufficiently broad as to be arguably supported by the authority provided. The citation can also be found at: Jones v. Singing River Health Sys., 2016 U.S. Dist. LEXIS 188753, *46 (M.D. Miss. June 2, 2016)."),
    ("102", "atty_fees", "ABC Supply Co., Inc. v. All in One Renovations LLC et al, 3:25-cv-00144-DMB-JMV.",
     "This decision represents a fact-specific determination and does not establish a binding ceiling for all litigation in this District.",
     "Yes", "green", False,
     "This citation was used in Defendant's brief, which Plaintiff now distinguishes. The proposition is sufficiently broad as to be arguably supported by the authority provided. The citation can also be found at: ABC Supply Co. v. All in One Renovations LLC, 2025 U.S. Dist. LEXIS 213307, *12-14 (N.D. Miss. Oct. 29, 2025)."),
    ("102", "atty_fees", "Missouri v. Jenkins, 491 U.S. 274, 288 n.10 (1989).",
     "The Supreme Court's caution against billing for purely secretarial tasks in Missouri v. Jenkins, 491 U.S. 274, 288 n.10 (1989), does not extend to essential professional activities, such as emailing or calling a client or reviewing and drafting legal documents.",
     "Yes", "green", True,
     "This is an arguable assertion. The note cited discusses how purely paralegal work cannot be assigned legal rates, just as clerical tasks cannot be assigned paralegal rates. However, the court does not define whether the instances cited in the proposition would constitute legal, paralegal, or clerical tasks."),
    ("102", "atty_fees", "Cruz v. Hauck, 762 F.2d 1230, 1233-34 (5th Cir. 1985).",
     "\"It would be inconsistent with the purpose of the fee-shifting statute to dilute a fees award by refusing to compensate the attorney for the time reasonably spent in establishing and negotiating his rightful claim to the fee.\"",
     "Yes", "yellow", False,
     "This is an inaccurate quote and is misleading. The real quote is: \"The time spent [] replying [to Defendants' objections] is compensable under § 1988. To hold otherwise would dilute the fee award and be inconsistent with the purposes of § 1988.\" However, the authority does broadly support the proposition."),
    ("105", "opp_msj", "Anderson v. Liberty Lobby, Inc., 477 U.S. 242, 248 (1986).",
     "\"A genuine issue of material fact exists when the evidence is such that a reasonable jury could return a verdict for the non-moving party.\"",
     "Yes", "yellow", False,
     "This is not a direct quote, although the authority directly supports the proposition. The direct quote is: \"summary judgment will not lie if the dispute about a material fact is 'genuine,' that is, if the evidence is such that a reasonable jury could return a verdict for the nonmoving party.\""),
    ("105", "opp_msj", "Matsushita Elec. Indus. Co. v. Zenith Radio Corp., 475 U.S. 574, 587 (1986).",
     "The court must view all evidence and draw all reasonable inferences in the light most favorable to the nonmoving party.",
     "Yes", "green", False, "None."),
    ("105", "opp_msj", "Celotex Corp. v. Catrett, 477 U.S. 317, 323 (1986).",
     "The moving party bears the initial burden of demonstrating the absence of a genuine issue of material fact.",
     "Yes", "green", False, "None."),
    ("105", "opp_msj", "City of Madison v. Bryan, 763 So. 2d 162, 166 (Miss. 2000).",
     "Mississippi courts have long held that a bill of exceptions statutory appeal is limited to challenges of a board's quasi-judicial or legislative actions, not its ministerial or administrative functions.",
     "Yes", "yellow", False,
     "The authority cited does not support the proposition. In fact, the court did not reach the issue of whether the appellant could appeal, by bill of exception, an alleged failure to act by a governing board of authorities of a municipality to a circuit court because it ruled appellate did not have standing anyway. It does not discuss quasi-judicial and legislative vs. ministerial and administrative actions by municipal bodies."),
    ("105", "opp_msj", "City of Grenada v. Harrelson, 84 So. 3d 35, 38 (Miss. Ct. App. 2012).",
     "As the Mississippi Court of Appeals has explained, the statute \"was not intended to be a vehicle for the litigation of a simple common law action for damages against a municipality.\"",
     "No", "red", True,
     "This seems to be an hallucinated case. The closest I could find was City of Grenada v. Harrelson, 725 So. 2d 770 (Miss. 1998). This case involved a declaratory judgment and injunctive relief action by a city against its city counsel for failing to properly adopt election procedures and districts. It does not mention bills of exceptions. The quote cannot be located, either."),
    # ---- page 6 (PageID 518) ----
    ("105", "opp_msj", "Crittendon v. State Farm Mut. Auto. Ins. Co., 99 So. 3d 751, 755 (Miss. 2012).",
     "The statute of limitations is an affirmative defense, and the City bears the burden of proving every element of that defense.",
     "No", "red", True,
     "This appears to be an hallucinated case. The citation 99 So.3d 751 is styled Watts v. Watts, 99 So.3d 751 (Miss. Ct. App. 2012) and discusses a chancellor's award of joint child custody."),
    ("105", "opp_msj", "Stringer v. Trapp, 30 So. 3d 339, 342 (Miss. 2010).",
     "Under Mississippi law, the question of when a plaintiff should have discovered an injury through the exercise of reasonable diligence is an issue of fact to be decided by a jury.",
     "Yes", "yellow", False,
     "The proposition is not supported by the authority. The Stringer court overturned a trial court's summary judgment ruling for the defendant because, even though the plaintiff exercised reasonable diligence in seeking her medical records to find the appropriate defendants, factual questions remained as to what the plaintiff knew and when. It does not discuss when a plaintiff should have discovered his/her injury, but when he/she discovered the names of the defendant he/she seeks to add past the statute of limitations deadline."),
    ("105", "opp_msj", "Young v. S. Farm Bureau Life Ins. Co., 592 So. 2d 103, 107 (Miss. 1991).",
     "\"The statute of limitations for a breach of contract claim begins to run at the time of the breach.\"",
     "Yes", "yellow", False,
     "This is not a direct quote, although the authority directly supports the proposition. The direct quote is: \"in the case of a breach of contract, the cause of action accrues at the time of the breach . . . .\""),
    ("105", "opp_msj", "See, e.g., Franconia Assocs. v. U.S., 536 U.S. 129, 143 (2002).",
     "(1) The right to sue accrues at the moment of breach, not on the mere suspicion that a breach might occur. (2) Franconia Assocs. v. U.S. holds that a claim for repudiation of a contract accrues at the time the repudiation is treated as a breach.",
     "Yes", "green", True,
     "(1) None. (2) This is a bit confusing. I believe the author is trying to say repudiation ripens into a breach prior to the time for performance if the promisee elects to treat it as a breach. If so, this proposition is supported by the authority."),
    ("108", "surreply", "See Doe v. City of Memphis, 928 F.3d 481, 491 (5th Cir. 2019).",
     "Courts in the Fifth Circuit routinely permit surreplies where a reply brief raises new issues to which the opposing party had no prior opportunity to respond.",
     "Yes", "yellow", False,
     "This is the correct citation for a case out of the 6th, not 5th, Circuit styled Doe v. City of Memphis, 928 F.3d 481 (6th Cir. 2019). However, this case dealt with whether the district court erred in striking the plaintiffs' class allegations before plaintiffs had a meaningful chance to pursue discovery. It does not discuss the procedural rules for surreplies, as the proposition suggests."),
    ("108", "surreply", "N. Cypress Med. Ctr. Operating Co. v. Cigna Healthcare, 781 F.3d 182, 203 (5th Cir. 2015).",
     "Courts in the Fifth Circuit routinely permit surreplies where a reply brief raises new issues to which the opposing party had no prior opportunity to respond.",
     "Yes", "yellow", False,
     "This authority does not support the proposition stated. The case primarily discusses whether a hospital has standing to enforce insurance contracts, the rights pursuant to which were assigned to it by their patients. It also discusses whether summary judgment was appropriate as to the plaintiffs' RICO claims. However, it does not provide support for the assertion surreplies are routinely permitted in the Fifth Circuit where the reply brief raises new issues."),
    ("108-1", "resp_surreply", "Cutrera v. Board of Supervisors of Louisiana State University, 429 F.3d 108 (5th Cir. 2005).",
     "The City's reliance on Cutrera v. Board of Supervisors of Louisiana State University, 429 F.3d 108 (5th Cir. 2005), is inapposite. That case stands for the unremarkable proposition that a plaintiff cannot raise an entirely new cause of action at the summary judgment stage.",
     "Yes", "yellow", False,
     "This citation was used in Defendant's brief, which Plaintiff now distinguishes. The Court did observe that a claim not raised in the complaint, but rather for the first time in response to a motion for summary judgment, is not properly before the Fifth Circuit Court, which broadly supports the distinctions plaintiff draws for the claims asserted in his complaint. However, this was not the sole issue that the Fifth Circuit decided in Cutrera, so it is somewhat misleading to state that Cutrera \"stands for\" the proposition that new causes of action cannot be raised for the first time at the summary judgment stage."),
    ("108-1", "resp_surreply", "Mississippi State Port Authority v. Yilport Holding A.S., 416 So. 3d 83 (Miss. 2025).",
     "Yilport reaffirmed the long-standing rule that a contract with a public board is formed only when entered on the minutes and that its terms cannot be varied by parol evidence.",
     "Yes", "green", False,
     "None. This citation was used in Defendant's brief, which Plaintiff now distinguishes. The correct pin cite for the distinction Plaintiff draws is Mississippi State Port Authority v. Yilport Holding A.S., 416 So. 3d 83, 89-90 (Miss. 2025) (rather than 88-89 as currently cited in the original brief)."),
    ("108-1", "resp_surreply", "Young v. S. Farm Bureau Life Ins. Co., 592 So. 2d 103, 107 (Miss. 1991).",
     "A cause of action for breach of contract accrues at the moment of a clear and unequivocal breach.",
     "Yes", "green", False,
     "None. This case evaluates when a breach of contract cause of action accrues in the context of an insurance contract. The court expressly observes its ruling is consistent with prior decisions where it held \"in the case of a breach of contract, the cause of action accrues at the time of the breach . . . .\" (citing Johnson v. Crisler, 156 Miss. 266, 269, 125 So. 724-725 (1930))."),
    ("108-1", "resp_surreply", "Stringer v. Trapp, 30 So. 3d 339, 342 (Miss. 2010).",
     "The determination of when Plaintiff knew or should have known of this final breach is a factual question that cannot be resolved on summary judgment.",
     "Yes", "green", False, "None."),
    # ---- page 7 (PageID 519) ----
    ("108-1", "resp_surreply", "Am. Tower Asset Sub, LLC v. Marshall Cnty., 324 So. 3d 300 (Miss. 2021).",
     "The City's citation to Am. Tower Asset Sub, LLC v. Marshall Cnty., 324 So. 3d 300 (Miss. 2021), does not alter this analysis. Am. Tower involved the type of quasi-judicial decision for which the statute was designed.",
     "Yes", "green", False,
     "None. This citation was used in Defendant's brief, which Plaintiff now distinguishes. Specifically, Plaintiff notes that this case involved an administrative body to which Miss. Code Ann. Section 11-51-75 applies."),
    ("108-1", "resp_surreply", "City of Grenada v. Harrelson, 84 So. 3d 35, 38 (Miss. Ct. App. 2012).",
     "the bill of exceptions statute \"was not intended to be a vehicle for the litigation of a simple common law action for damages against a municipality.\"",
     "No", "red", True,
     "This seems to be the same hallucinated case at issue in Doc. 105."),
]


def main() -> None:
    out = Path(__file__).parent / "data" / "withers_aberdeen_corpus.csv"
    fields = ["row_id", "doc_number", "pleading", "citation", "proposition",
              "exists", "label", "hedged", "irregularity"]
    with out.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(fields)
        for i, (doc, pleading, cite, prop, exists, label, hedged, irreg) in enumerate(ROWS, 1):
            w.writerow([f"withers-{i:02d}", doc, pleading, cite, prop,
                        exists, label, "yes" if hedged else "no", irreg])

    # Summary
    from collections import Counter
    labels = Counter(r[5] for r in ROWS)
    exists = Counter(r[4] for r in ROWS)
    hedged = sum(1 for r in ROWS if r[6])
    print(f"Wrote {len(ROWS)} rows -> {out}")
    print(f"  label:  {dict(labels)}")
    print(f"  exists: {dict(exists)}")
    print(f"  hedged: {hedged}")


if __name__ == "__main__":
    main()
