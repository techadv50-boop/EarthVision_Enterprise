import { useState, type InputHTMLAttributes } from 'react';

type Props = InputHTMLAttributes<HTMLInputElement> & {
  [key: `data-${string}`]: string | undefined;
};

/**
 * Fields that must not be stored by Chrome, Google Password Manager, or other
 * vaults. A real password input next to an email or username makes the browser
 * save that pair for satpass.xdgen.com and offer every saved account — including
 * in Incognito and other browsers signed into the same Google account.
 */
function vaultProps(name: string): Props {
  return {
    name,
    // Chrome ignores "off" on anything it decides is a login field and then
    // shows every saved account. "one-time-code" is a value it still honors.
    autoComplete: 'one-time-code',
    autoCapitalize: 'none',
    autoCorrect: 'off',
    spellCheck: false,
    'data-lpignore': 'true',
    'data-1p-ignore': 'true',
    'data-bwignore': 'true',
    'data-form-type': 'other',
  };
}

export function QuietTextInput({ className = '', onFocus, name = 'satpass-id', ...rest }: Props) {
  const [armed, setArmed] = useState(false);
  return (
    <input
      {...rest}
      {...vaultProps(name)}
      type="text"
      readOnly={!armed}
      className={className}
      onFocus={(e) => {
        e.currentTarget.readOnly = false;
        setArmed(true);
        onFocus?.(e);
      }}
    />
  );
}

export function QuietSecretInput({ className = '', onFocus, ...rest }: Props) {
  const [armed, setArmed] = useState(false);
  return (
    <input
      {...rest}
      {...vaultProps('satpass-secret')}
      type="text"
      readOnly={!armed}
      className={`${className} quiet-secret`}
      onFocus={(e) => {
        e.currentTarget.readOnly = false;
        setArmed(true);
        onFocus?.(e);
      }}
    />
  );
}
