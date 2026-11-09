import { Component, type ReactNode } from 'react';
import { Button } from '@fluentui/react-components';
import { track } from './telemetry';

export class TelemetryBoundary extends Component<{ children: ReactNode }, { failed: boolean }> {
  state = { failed: false };

  static getDerivedStateFromError(): { failed: boolean } {
    return { failed: true };
  }

  componentDidCatch(error: Error): void {
    track(
      'portal_browser_error',
      {
        errorCategory: 'render_error',
        errorName: error.name,
      },
    );
  }

  render(): ReactNode {
    if (this.state.failed)
      return (
        <main className="welcome">
          <div className="welcome-card">
            <h1>Unable to display the portal</h1>
            <p role="alert">Reload to retry. Check the API state before repeating any change.</p>
            <Button onClick={() => window.location.reload()}>Reload portal</Button>
          </div>
        </main>
      );
    return this.props.children;
  }
}
