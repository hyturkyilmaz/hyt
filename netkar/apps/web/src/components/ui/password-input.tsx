'use client';

import { Eye, EyeOff } from 'lucide-react';
import * as React from 'react';

import { Input } from '@/components/ui/input';
import { cn } from '@/lib/utils';

type PasswordInputProps = Omit<React.InputHTMLAttributes<HTMLInputElement>, 'type'>;

// Parola göster/gizle düğmesi: 44px hedef, aria-pressed ile durum bildirir.
const PasswordInput = React.forwardRef<HTMLInputElement, PasswordInputProps>(
  ({ className, ...props }, ref) => {
    const [visible, setVisible] = React.useState(false);
    return (
      <div className="relative">
        <Input
          ref={ref}
          type={visible ? 'text' : 'password'}
          className={cn('pr-14', className)}
          autoCapitalize="none"
          autoCorrect="off"
          spellCheck={false}
          {...props}
        />
        <button
          type="button"
          onClick={() => setVisible((value) => !value)}
          aria-pressed={visible}
          aria-label={visible ? 'Parolayı gizle' : 'Parolayı göster'}
          className="absolute right-0 top-0 inline-flex size-touch items-center justify-center rounded-md text-muted-foreground hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
        >
          {visible ? (
            <EyeOff className="size-5" aria-hidden="true" />
          ) : (
            <Eye className="size-5" aria-hidden="true" />
          )}
        </button>
      </div>
    );
  },
);
PasswordInput.displayName = 'PasswordInput';

export { PasswordInput };
