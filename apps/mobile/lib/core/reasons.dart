/// Reason codes turned into plain, non-clinical English.
///
/// The codes themselves are the contract; this mapping is presentation. Any
/// code without an entry is dropped rather than shown raw, so a new backend
/// code can never surface as debug text in front of a user.
const Map<String, String> _reasonText = <String, String>{
  'goal_sleep': 'you want to wind down for sleep',
  'goal_overthinking': 'your mind is busy',
  'goal_stress': 'you want to settle stress',
  'goal_focus': 'you want steadier attention',
  'goal_emotional_reset': 'you want an emotional reset',
  'goal_general': 'you are practising generally',
  'high_mental_activity': 'your thinking is running fast right now',
  'high_stress': 'stress is high right now',
  'very_high_stress': 'stress is very high right now',
  'moderate_stress': 'stress is moderate right now',
  'high_sleepiness': 'you are feeling sleepy',
  'grounding_preferred': 'attention settles more easily in the body',
  'cognitive_observation': 'watching thoughts suits a busy mind',
  'stabilize_attention': 'the breath gives attention one steady place',
  'experienced_open_awareness':
      'you have enough experience for an open practice',
  'recognize_reactivity': 'noticing feeling tone catches reactions early',
  'experience_progression': 'this matches your experience level',
  'fallback_practice_used': 'the closest available practice was chosen',
};

/// The longer form used by the `contextual` variant.
///
/// Adds one sentence of framing before the reasons. It says nothing the
/// `concise` form does not; the experiment is about whether the extra framing
/// helps, not about telling one group something different.
const Map<String, String> _contextualLeadIn = <String, String>{
  'goal_sleep': 'Winding down works better from the body than from the head.',
  'goal_overthinking':
      'A busy mind settles faster with something concrete to rest on.',
  'goal_stress':
      'Stress eases when attention has one steady place to return to.',
  'goal_focus': 'Attention steadies when it has a single anchor.',
  'goal_emotional_reset':
      'Strong feeling passes more easily when it is met rather than pushed away.',
  'goal_general':
      'A regular practice builds on what you already find workable.',
};

/// The explanation for a recommendation, in the requested variant.
///
/// `variant` affects wording only. The practice, duration and guidance density
/// are decided by the backend engine and are not passed through here at all.
String? explainRecommendationVariant(
  String practiceName,
  List<String> reasonCodes, {
  String variant = 'concise',
}) {
  final String? base = explainRecommendation(practiceName, reasonCodes);
  if (base == null || variant != 'contextual') {
    return base;
  }
  final String? leadIn = reasonCodes
      .map((String code) => _contextualLeadIn[code])
      .firstWhere((String? value) => value != null, orElse: () => null);
  return leadIn == null ? base : '$leadIn $base';
}

/// One sentence explaining a recommendation, or null when nothing is known.
String? explainRecommendation(String practiceName, List<String> reasonCodes) {
  final List<String> parts = <String>[
    for (final String code in reasonCodes)
      if (_reasonText.containsKey(code)) _reasonText[code]!,
  ];
  if (parts.isEmpty) {
    return null;
  }
  if (parts.length == 1) {
    return '$practiceName, because ${parts.first}.';
  }
  final String last = parts.removeLast();
  return '$practiceName, because ${parts.join(', ')} and $last.';
}
