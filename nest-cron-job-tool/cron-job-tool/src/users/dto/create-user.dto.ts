import { IsEmail, IsNotEmpty, MaxLength } from'class-validator';

/**
 * 接收用户传过来的参数，进行校验
 */
export class CreateUserDto {
    @IsNotEmpty()
    @MaxLength(50)
    name: string;

    @IsNotEmpty()
    @IsEmail()
    @MaxLength(50)
    email: string;
}