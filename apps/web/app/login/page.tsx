import { Suspense } from "react";

import MemberPhoneAuthForm from "@/components/MemberPhoneAuthForm";

export const dynamic = "force-dynamic";

export default function LoginPage() {
  return (
    <Suspense>
      <MemberPhoneAuthForm intent="login" />
    </Suspense>
  );
}
