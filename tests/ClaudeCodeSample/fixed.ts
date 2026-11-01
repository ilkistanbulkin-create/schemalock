import { PrismaClient } from "@prisma/client";

const prisma = new PrismaClient();

export async function getUser(id: number) {
  // 'userId' does not exist on User; the column is 'id'.
  return prisma.user.findFirst({
    where: { id: id },
    select: { email: true, name: true },
  });
}
