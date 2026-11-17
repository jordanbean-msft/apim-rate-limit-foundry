"""Any administrable configuration record, discriminated by its distinct required fields."""

from apim_rate_limit_foundry.models import Assignment, Budget, Organization, Price

ConfigRecord = Organization | Assignment | Budget | Price
