import { useEffect, useState } from 'react';

function initials(name: string) {
  const parts = name.trim().split(/\s+/).filter(Boolean);
  return parts.length > 1
    ? `${parts[0][0]}${parts[parts.length - 1][0]}`.toUpperCase()
    : (parts[0]?.slice(0, 2).toUpperCase() ?? '?');
}

export function ProfileGreeting({
  name,
  cloud,
  getGraphToken,
}: {
  name: string;
  cloud: 'commercial' | 'government';
  getGraphToken: () => Promise<string>;
}) {
  const [displayName, setDisplayName] = useState(name);
  const [photoUrl, setPhotoUrl] = useState('');

  useEffect(() => {
    let active = true;
    let objectUrl = '';
    setDisplayName(name);
    setPhotoUrl('');
    const graphOrigin =
      cloud === 'government' ? 'https://graph.microsoft.us' : 'https://graph.microsoft.com';

    async function loadProfile() {
      try {
        const token = await getGraphToken();
        const headers = { Authorization: `Bearer ${token}` };
        const [profileResult, photoResult] = await Promise.allSettled([
          fetch(`${graphOrigin}/v1.0/me?$select=displayName`, {
            headers,
            credentials: 'omit',
            cache: 'no-store',
          }),
          fetch(`${graphOrigin}/v1.0/me/photo/$value`, {
            headers,
            credentials: 'omit',
            cache: 'no-store',
          }),
        ]);
        if (active && profileResult.status === 'fulfilled' && profileResult.value.ok) {
          try {
            const profile: unknown = await profileResult.value.json();
            if (
              active &&
              typeof profile === 'object' &&
              profile !== null &&
              'displayName' in profile &&
              typeof profile.displayName === 'string' &&
              profile.displayName.trim()
            ) {
              setDisplayName(profile.displayName.trim());
            }
          } catch {
            // An optional Graph name lookup must not suppress a valid photo.
          }
        }
        if (active && photoResult.status === 'fulfilled' && photoResult.value.ok) {
          const photo = await photoResult.value.blob();
          if (
            active &&
            photo.type.startsWith('image/') &&
            photo.size > 0 &&
            photo.size <= 5 * 1024 * 1024
          ) {
            objectUrl = URL.createObjectURL(photo);
            setPhotoUrl(objectUrl);
          }
        }
      } catch {
        // Graph consent and profile-photo availability are optional for portal access.
      }
    }

    void loadProfile();
    return () => {
      active = false;
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [cloud, getGraphToken, name]);

  return (
    <div className="profile-greeting" aria-label="Signed-in profile">
      {photoUrl ? (
        <img className="profile-photo" src={photoUrl} alt="" />
      ) : (
        <span className="profile-initials" aria-hidden="true">
          {initials(displayName)}
        </span>
      )}
      <span>Howdy {displayName}!</span>
    </div>
  );
}
