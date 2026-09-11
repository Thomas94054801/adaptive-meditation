import 'package:flutter/material.dart';

import '../check_in/check_in_screen.dart';
import '../history/history_screen.dart';

/// Entry point. No registration wall: the primary action starts a session.
class WelcomeScreen extends StatelessWidget {
  const WelcomeScreen({super.key});

  @override
  Widget build(BuildContext context) {
    final ThemeData theme = Theme.of(context);
    return Scaffold(
      body: SafeArea(
        // Scrolls only when it has to. At normal text sizes the Spacers lay the
        // screen out as designed; at large Dynamic Type settings the content is
        // taller than the viewport and would otherwise overflow, which the
        // accessibility baseline caught at 2x scale.
        child: LayoutBuilder(
          builder: (BuildContext context, BoxConstraints constraints) => SingleChildScrollView(
            padding: const EdgeInsets.symmetric(horizontal: 24, vertical: 32),
            child: ConstrainedBox(
              constraints: BoxConstraints(
                minHeight: constraints.maxHeight - 64,
              ),
              child: IntrinsicHeight(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.stretch,
                  children: <Widget>[
                    const Spacer(),
                    Semantics(
                      header: true,
                      child: Text(
                        'Adaptive Meditation',
                        style: theme.textTheme.headlineMedium?.copyWith(
                          fontWeight: FontWeight.w600,
                        ),
                      ),
                    ),
                    const SizedBox(height: 12),
                    Text(
                      'Tell the app how you are right now. It chooses a practice to '
                      'match, and you can start in under a minute.',
                      style: theme.textTheme.bodyLarge,
                    ),
                    const Spacer(),
                    Semantics(
                      button: true,
                      label: 'Start a session. No account is needed.',
                      child: FilledButton(
                        key: const Key('welcome_start'),
                        onPressed: () => Navigator.of(context).push<void>(
                          MaterialPageRoute<void>(
                            builder: (BuildContext context) =>
                                const CheckInScreen(),
                          ),
                        ),
                        child: const Text('Start a session'),
                      ),
                    ),
                    const SizedBox(height: 12),
                    Text(
                      'Continue as guest. No account needed.',
                      textAlign: TextAlign.center,
                      style: theme.textTheme.bodyMedium?.copyWith(
                        color: theme.colorScheme.onSurfaceVariant,
                      ),
                    ),
                    const SizedBox(height: 20),
                    TextButton(
                      key: const Key('welcome_history'),
                      onPressed: () => Navigator.of(context).push<void>(
                        MaterialPageRoute<void>(
                          builder: (BuildContext context) =>
                              const HistoryScreen(),
                        ),
                      ),
                      child: const Text('Your sessions'),
                    ),
                    const SizedBox(height: 8),
                    // The one wellness disclaimer surface. Shown here, once, rather
                    // than repeated on every screen: a warning that appears
                    // everywhere stops being read, which makes the product worse
                    // without making it safer.
                    Semantics(
                      container: true,
                      child: Text(
                        'A wellness practice app. It does not diagnose or treat any '
                        'medical condition, and it cannot help in an emergency.',
                        key: const Key('welcome_disclaimer'),
                        textAlign: TextAlign.center,
                        style: theme.textTheme.bodySmall?.copyWith(
                          color: theme.colorScheme.onSurfaceVariant,
                        ),
                      ),
                    ),
                  ],
                ),
              ),
            ),
          ),
        ),
      ),
    );
  }
}
